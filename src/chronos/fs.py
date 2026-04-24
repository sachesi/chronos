from __future__ import annotations

import fcntl
import errno
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from .config import backup_dest, expand_user_path
from .output import warn
from .types import ChronosError, ConfigJob, FilesystemInfo, MetadataDecision, SELinuxInfo

# Filesystem types that do not support extended attributes.
NO_XATTR_FSTYPES = {
    "vfat", "msdos", "fat", "exfat",
    "ntfs", "ntfs3", "fuseblk",
    "iso9660", "udf",
}

# Filesystem types that do not support POSIX ACLs.
NO_ACL_FSTYPES = NO_XATTR_FSTYPES.copy()

# Rsync xattr filter rules to exclude SELinux security.* labels on both sides,
# avoiding rsync_xal_set/lremovexattr permission spam on backup filesystems.
SELINUX_XATTR_FILTER_RULES = ["-xs security.*", "-xr security.*"]


# ---------------------------------------------------------------------------
# Process/tool helpers
# ---------------------------------------------------------------------------

def run_capture(argv: list[str]) -> str:
    proc = subprocess.run(
        argv, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def is_mountpoint(path: str | Path) -> bool:
    return subprocess.run(["mountpoint", "-q", str(path)], check=False).returncode == 0


def require_tool(name: str) -> None:
    import shutil
    if shutil.which(name) is None:
        raise ChronosError(f"missing required command: {name}")


# ---------------------------------------------------------------------------
# Backup directory safety
# ---------------------------------------------------------------------------

def ensure_backup_mount(backup_dir: Path, require_mount: bool) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not require_mount:
        return
    mount_target = run_capture(
        ["findmnt", "-n", "-o", "TARGET", "--target", str(backup_dir)]
    )
    if not mount_target or mount_target == "/":
        raise ChronosError(
            f"{backup_dir} is not on a mounted backup filesystem. "
            "Mount the backup disk or change backup_dir in config."
        )


def lock_path_for_scope(config: dict[str, Any], kind: str) -> Path:
    backup_dir = expand_user_path(config["backup_dir"])
    if kind == "system":
        return backup_dir / ".chronos-system.lock"
    if kind == "user":
        return backup_dir / ".chronos-user.lock"
    raise ChronosError(f"unknown lock scope: {kind}")


def lock_path_for_target(config: dict[str, Any], target: str) -> Path:
    return backup_dest(config, target) / ".chronos-target.lock"


def scope_lock_kind(job: ConfigJob, config: dict[str, Any], targets: list[str]) -> str:
    if job.scope == "system":
        return "system"
    if any(bool(config["targets"][target].get("requires_root", False)) for target in targets):
        return "system"
    return "user"


@contextmanager
def _acquire_lock(lock_path: Path, *, open_error: str, conflict_error: str) -> Generator[None, None, None]:
    fd = None
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o660)
    except PermissionError:
        raise ChronosError(f"{open_error}: permission denied") from None
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise ChronosError(f"{open_error}: {detail}") from None

    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES}:
                raise ChronosError(conflict_error) from None
            detail = exc.strerror or str(exc)
            raise ChronosError(f"cannot lock {lock_path}: {detail}") from None
        yield
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)


@contextmanager
def backup_scope_lock(
    config: dict[str, Any], job: ConfigJob, targets: list[str]
) -> Generator[None, None, None]:
    kind = scope_lock_kind(job, config, targets)
    lock_path = lock_path_for_scope(config, kind)
    backup_dir = expand_user_path(config["backup_dir"])
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        raise ChronosError(f"cannot create backup directory {backup_dir}: permission denied") from None
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise ChronosError(f"cannot create backup directory {backup_dir}: {detail}") from None

    if kind == "system":
        open_error = f"cannot create/open system backup lock {lock_path}"
        conflict_error = f"another chronos system backup is already running for {backup_dir}"
    else:
        open_error = (
            f"cannot create/open user backup lock {lock_path}. "
            "Ensure backup_dir is writable for user backups (group-writable), "
            "or use a user-writable backup_dir"
        )
        conflict_error = f"another chronos user backup is already running for {backup_dir}"

    with _acquire_lock(lock_path, open_error=open_error, conflict_error=conflict_error):
        yield


@contextmanager
def target_lock(config: dict[str, Any], target: str) -> Generator[None, None, None]:
    lock_path = lock_path_for_target(config, target)
    target_root = lock_path.parent
    try:
        target_root.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        raise ChronosError(f"cannot create target directory {target_root}: permission denied") from None
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise ChronosError(f"cannot create target directory {target_root}: {detail}") from None

    open_error = f"cannot create/open target lock {lock_path}"
    conflict_error = (
        "another chronos operation is already touching "
        f"target {target} at {target_root}"
    )
    with _acquire_lock(lock_path, open_error=open_error, conflict_error=conflict_error):
        yield


# ---------------------------------------------------------------------------
# SELinux detection
# ---------------------------------------------------------------------------

def selinux_info() -> SELinuxInfo:
    selinux_dir = Path("/sys/fs/selinux")
    config = Path("/etc/selinux/config")
    present = selinux_dir.exists() or config.exists()
    enforce_file = selinux_dir / "enforce"
    if enforce_file.exists():
        try:
            enforcing = enforce_file.read_text(encoding="utf-8").strip() == "1"
        except OSError:
            enforcing = None
        return SELinuxInfo(present=True, enabled=True, enforcing=enforcing)
    return SELinuxInfo(present=present, enabled=False, enforcing=None)


# ---------------------------------------------------------------------------
# Filesystem probing
# ---------------------------------------------------------------------------

def filesystem_info(path: str | Path) -> FilesystemInfo:
    p = expand_user_path(path)
    output = run_capture(
        ["findmnt", "-n", "-T", str(p), "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"]
    )
    if not output:
        return FilesystemInfo(path=p)
    parts = output.split(maxsplit=3)
    while len(parts) < 4:
        parts.append("")
    target, source, fstype, options = parts[0], parts[1], parts[2], parts[3]
    return FilesystemInfo(
        path=p, target=target, source=source, fstype=fstype.lower(), options=options
    )


def can_write_user_xattr(directory: Path) -> bool | None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    try:
        with tempfile.NamedTemporaryFile(prefix=".chronos-xattr-", dir=directory) as f:
            os.setxattr(f.name, b"user.chronos_test", b"1")
            os.removexattr(f.name, b"user.chronos_test")
        return True
    except (OSError, AttributeError):
        return False


def can_manage_selinux_xattr(directory: Path) -> bool | None:
    """Return whether rsync can safely set/remove security.selinux on this destination.

    user.* xattr support is not enough for SELinux labels. Backup directories under
    /mnt often support normal xattrs but SELinux policy still denies writes/removals
    of security.selinux, which makes rsync -X fail with code 23.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    try:
        with tempfile.NamedTemporaryFile(prefix=".chronos-selinux-", dir=directory) as f:
            name = f.name
            try:
                current = os.getxattr(name, b"security.selinux")
            except OSError:
                return False
            try:
                os.setxattr(name, b"security.selinux", current)
            except OSError:
                return False
            try:
                os.removexattr(name, b"security.selinux")
            except OSError:
                return False
        return True
    except (OSError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Metadata decision
# ---------------------------------------------------------------------------

def fs_likely_supports_xattrs(fs: FilesystemInfo) -> bool:
    return fs.fstype not in NO_XATTR_FSTYPES


def fs_likely_supports_acls(fs: FilesystemInfo) -> bool:
    return fs.fstype not in NO_ACL_FSTYPES


def selinux_xattr_policy(config: dict[str, Any]) -> str:
    value = str(config.get("selinux_xattrs", "auto")).lower()
    if value not in {"auto", "preserve", "exclude"}:
        raise ChronosError("selinux_xattrs must be one of: auto, preserve, exclude")
    return value


def requested_bool(
    config: dict[str, Any], target_config: dict[str, Any], key: str, default: bool
) -> bool:
    return bool(target_config.get(key, config.get(key, default)))


def decide_metadata(
    config: dict[str, Any],
    target_config: dict[str, Any],
    source_fs: FilesystemInfo,
    dest_fs: FilesystemInfo,
    *,
    dest_path: Path,
    mode: str,
    selinux: SELinuxInfo | None = None,
) -> MetadataDecision:
    preserve_acls = requested_bool(config, target_config, "preserve_acls", True)
    preserve_xattrs = requested_bool(config, target_config, "preserve_xattrs", True)
    xattr_filter_rules: list[str] = []
    selinux_label_action = "not-requested"

    if not config.get("check_filesystems", True):
        return MetadataDecision(
            preserve_acls=preserve_acls,
            preserve_xattrs=preserve_xattrs,
            xattr_filter_rules=xattr_filter_rules,
            selinux_label_action=selinux_label_action,
        )

    src_acl_ok = fs_likely_supports_acls(source_fs)
    dst_acl_ok = fs_likely_supports_acls(dest_fs)
    src_xattr_ok = fs_likely_supports_xattrs(source_fs)
    dst_xattr_ok = fs_likely_supports_xattrs(dest_fs)

    xattr_probe = can_write_user_xattr(dest_path)
    if xattr_probe is not None:
        dest_fs.writable_xattr = xattr_probe
        dst_xattr_ok = dst_xattr_ok and xattr_probe

    auto_disable = config.get("auto_disable_unsupported_metadata", True)

    if preserve_acls and (not src_acl_ok or not dst_acl_ok):
        message = (
            f"ACL preservation is not supported for this {mode} path "
            f"({source_fs.fstype} -> {dest_fs.fstype})"
        )
        if auto_disable:
            warn(message + "; disabling -A for this target")
            preserve_acls = False
        else:
            raise ChronosError(message)

    if preserve_xattrs and (not src_xattr_ok or not dst_xattr_ok):
        message = (
            f"xattr preservation is not supported for this {mode} path "
            f"({source_fs.fstype} -> {dest_fs.fstype})"
        )
        if auto_disable:
            warn(message + "; disabling -X for this target")
            preserve_xattrs = False
        else:
            raise ChronosError(message)

    policy = selinux_xattr_policy(config)
    selinux_relevant = bool(selinux and selinux.present and preserve_xattrs)
    if selinux_relevant:
        if policy in {"auto", "exclude"}:
            xattr_filter_rules.extend(SELINUX_XATTR_FILTER_RULES)
            selinux_label_action = (
                "excluded automatically" if policy == "auto" else "excluded by config"
            )
        else:
            can_manage = can_manage_selinux_xattr(dest_path)
            if can_manage:
                selinux_label_action = "preserved"
            else:
                raise ChronosError(
                    "destination allows normal xattrs but does not allow managing "
                    "security.selinux labels; rsync -X would likely fail with code 23"
                )

    return MetadataDecision(
        preserve_acls=preserve_acls,
        preserve_xattrs=preserve_xattrs,
        xattr_filter_rules=xattr_filter_rules,
        selinux_label_action=selinux_label_action,
    )


def warn_selinux_metadata_loss(
    selinux: SELinuxInfo, target: str, metadata: MetadataDecision, *, show: bool = False
) -> None:
    if not show:
        return
    if not selinux.present:
        return
    if target not in ("root", "home"):
        return
    if not metadata.preserve_xattrs:
        warn(
            "SELinux is present, but xattrs are not being preserved for this target; "
            "restores may need relabeling and exact labels will not be stored in the backup"
        )
    elif metadata.selinux_label_action.startswith("excluded"):
        warn(
            "SELinux/security.* xattrs are excluded for this target, but other xattrs are "
            "still preserved; root restores will use .autorelabel to regenerate labels"
        )
