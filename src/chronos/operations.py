from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .config import backup_dest, expand_user_path, extra_info_enabled
from .fs import (
    decide_metadata,
    filesystem_info,
    selinux_xattr_policy,
    warn_selinux_metadata_loss,
)
from .output import info, ok, warn
from .rsync import (
    append_excludes,
    backup_excludes_for_target,
    build_rsync_args,
    choose_source,
    effective_progress_style,
    ensure_trailing_slash,
    run_rsync,
)
from .types import ChronosError, Plan, SELinuxInfo
from .versioning import (
    create_version_dir,
    is_target_versioned,
    prune_old_versions,
    resolve_current_version,
    source_for_restore,
    target_versions_dir,
    update_current_symlink,
    is_relative_to,
)


# ---------------------------------------------------------------------------
# Restore path helpers
# ---------------------------------------------------------------------------

def join_restore_root(restore_root: str | Path, subpath: str | Path) -> Path:
    root = expand_user_path(restore_root)
    sub = str(subpath)
    if sub.startswith("/"):
        sub = sub[1:]
    if str(root) == "/":
        return Path("/") / sub
    return root / sub


def efi_restore_destination(config: dict[str, Any]) -> Path:
    restore_root = expand_user_path(config["restore_root"])
    candidates = [
        join_restore_root(restore_root, "efi"),
        join_restore_root(restore_root, "boot/efi"),
    ]
    for candidate in candidates:
        if candidate.exists() and _is_mountpoint(candidate):
            return candidate
    fallback = candidates[0]
    fallback.mkdir(parents=True, exist_ok=True)
    if not _is_mountpoint(fallback):
        raise ChronosError(f"{fallback} is not a mounted EFI System Partition")
    return fallback


def restore_destination(config: dict[str, Any], target: str) -> Path:
    if target == "efi":
        return efi_restore_destination(config)
    restore_root = expand_user_path(config["restore_root"])
    if target == "root":
        return restore_root
    src_expanded = expand_user_path(config["targets"][target].get("src", f"/{target}"))
    return join_restore_root(restore_root, str(src_expanded).strip("/"))


def create_restore_dirs(config: dict[str, Any], target: str) -> None:
    if target != "root":
        return
    restore_root = expand_user_path(config["restore_root"])
    for d in config["targets"]["root"].get("create_dirs_after_restore", []):
        join_restore_root(restore_root, d).mkdir(parents=True, exist_ok=True)


def should_touch_autorelabel(config: dict[str, Any], selinux: SELinuxInfo) -> bool:
    value = config.get("touch_autorelabel", "auto")
    if isinstance(value, bool):
        return value
    if str(value).lower() != "auto":
        return False
    restore_root = expand_user_path(config["restore_root"])
    return selinux.present or join_restore_root(restore_root, "etc/selinux").exists()


# ---------------------------------------------------------------------------
# Restore confirmation
# ---------------------------------------------------------------------------

def confirm_restore(config: dict[str, Any], plan: Plan, targets: list[str]) -> None:
    if plan.mode != "restore" or plan.yes or plan.dry_run:
        return
    if not config.get("confirm_restore_to_live_root", True):
        return

    restore_root = str(expand_user_path(config["restore_root"]))
    print()
    warn(f"restore will write to: {restore_root}")
    warn(f"targets: {', '.join(targets)}")
    if restore_root == "/":
        warn("this is the live running system root")
    if plan.no_interactive:
        raise ChronosError("restore requires confirmation; re-run with --yes")
    answer = input("Type RESTORE to continue: ").strip()
    if answer != "RESTORE":
        raise ChronosError("restore cancelled")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup_target(
    config: dict[str, Any], target: str, *, dry_run: bool, selinux: SELinuxInfo
) -> None:
    target_config = config["targets"][target]
    src = choose_source(target, target_config)
    destination_for_rsync = backup_dest(config, target)
    created_version: str | None = None
    incomplete_dir: Path | None = None
    final_version_dir: Path | None = None
    link_dest: Path | None = None

    if is_target_versioned(target_config):
        created_version, incomplete_dir, final_version_dir = create_version_dir(config, target)
        destination_for_rsync = incomplete_dir
        try:
            link_dest = resolve_current_version(config, target)
        except ChronosError as exc:
            warn(str(exc))
            link_dest = None
    else:
        destination_for_rsync.mkdir(parents=True, exist_ok=True)

    show_extra = extra_info_enabled(config)
    if show_extra:
        info(f"[{target}] source:      {src}")
        info(f"[{target}] destination: {destination_for_rsync}")

    source_fs = filesystem_info(src)
    dest_fs = filesystem_info(destination_for_rsync)
    if show_extra:
        info(f"[{target}] source fs:   {source_fs.summary()}")
        info(f"[{target}] dest fs:     {dest_fs.summary()}")

    metadata = decide_metadata(
        config, target_config, source_fs, dest_fs,
        dest_path=destination_for_rsync, mode="backup", selinux=selinux,
    )
    if show_extra and metadata.preserve_xattrs and selinux.present and target in ("root", "home"):
        info(f"SELinux xattrs: {metadata.selinux_label_action}")
    warn_selinux_metadata_loss(selinux, target, metadata, show=show_extra)

    args = build_rsync_args(config, target_config, mode="backup", metadata=metadata)
    if is_target_versioned(target_config) and link_dest is not None:
        try:
            base_real = target_versions_dir(config, target).resolve()
            link_real = link_dest.resolve()
            if is_relative_to(link_real, base_real):
                args.append(f"--link-dest={link_real}")
            else:
                warn(f"cannot safely use --link-dest for {target}; falling back to full copy")
        except OSError:
            warn(f"cannot safely resolve previous version for {target}; falling back to full copy")

    append_excludes(args, backup_excludes_for_target(config, target, target_config))
    args.extend([ensure_trailing_slash(src), ensure_trailing_slash(destination_for_rsync)])

    try:
        run_rsync(
            args,
            dry_run=dry_run,
            progress_style=effective_progress_style(config),
            show_command=show_extra,
        )
    except Exception:
        if incomplete_dir is not None:
            shutil.rmtree(incomplete_dir, ignore_errors=True)
        raise

    if is_target_versioned(target_config):
        assert created_version is not None
        assert incomplete_dir is not None
        assert final_version_dir is not None
        if not dry_run:
            incomplete_dir.rename(final_version_dir)
            update_current_symlink(config, target, created_version)
            keep_versions = int(target_config.get("keep_versions", 10))
            prune_old_versions(config, target, keep_versions)
        else:
            shutil.rmtree(incomplete_dir, ignore_errors=True)

    if show_extra:
        ok(f"backup finished: {target}")


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def restore_target(
    config: dict[str, Any],
    target: str,
    *,
    dry_run: bool,
    selinux: SELinuxInfo,
    requested_version: str | None = None,
) -> None:
    target_config = config["targets"][target]
    src = source_for_restore(config, target, requested_version)
    if not src.exists():
        raise ChronosError(f"missing backup: {src}")
    dst = restore_destination(config, target)
    dst.mkdir(parents=True, exist_ok=True)
    create_restore_dirs(config, target)

    show_extra = extra_info_enabled(config)
    if show_extra:
        info(f"[{target}] source:      {src}")
        info(f"[{target}] destination: {dst}")

    source_fs = filesystem_info(src)
    dest_fs = filesystem_info(dst)
    if show_extra:
        info(f"[{target}] source fs:   {source_fs.summary()}")
        info(f"[{target}] dest fs:     {dest_fs.summary()}")

    metadata = decide_metadata(
        config, target_config, source_fs, dest_fs,
        dest_path=dst, mode="restore", selinux=selinux,
    )
    if show_extra and metadata.preserve_xattrs and selinux.present and target in ("root", "home"):
        info(f"SELinux xattrs: {metadata.selinux_label_action}")
    warn_selinux_metadata_loss(selinux, target, metadata, show=show_extra)

    args = build_rsync_args(config, target_config, mode="restore", metadata=metadata)
    append_excludes(args, target_config.get("restore_exclude", []))
    args.extend([ensure_trailing_slash(src), ensure_trailing_slash(dst)])
    run_rsync(
        args,
        dry_run=dry_run,
        progress_style=effective_progress_style(config),
        show_command=show_extra,
    )

    if target == "root" and should_touch_autorelabel(config, selinux):
        try:
            join_restore_root(config["restore_root"], ".autorelabel").touch(exist_ok=True)
            ok("created .autorelabel for SELinux relabel on next boot")
        except OSError:
            warn("could not create .autorelabel")

    if show_extra:
        ok(f"restore finished: {target}")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_mountpoint(path: Path) -> bool:
    from .fs import is_mountpoint
    return is_mountpoint(path)
