from __future__ import annotations

import os
import pwd
import re
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

from .output import ok
from .types import ChronosError, ConfigJob, Plan

APP_NAME = "chronos"

SYSTEM_CONFIG_PATH = Path("/etc/chronos/config.toml")
SYSTEM_CONFIG_DROPIN_DIR = Path("/etc/chronos/config.toml.d")

TARGET_ALIASES: dict[str, str] = {
    "/": "root",
    "root": "root",
    "/home": "home",
    "home": "home",
    "efi": "efi",
    "esp": "efi",
    "/efi": "efi",
    "/boot/efi": "efi",
    "boot": "boot",
    "/boot": "boot",
    "a": "all",
    "all": "all",
}

TARGET_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
RESERVED_TARGET_NAMES = {"all", "a"}

ALLOWED_TOP_LEVEL_KEYS = {
    "backup_dir",
    "restore_root",
    "all_targets",
    "confirm_restore_to_live_root",
    "require_backup_mount",
    "check_filesystems",
    "auto_disable_unsupported_metadata",
    "touch_autorelabel",
    "selinux_xattrs",
    "delete",
    "delete_excluded",
    "exclude_container_storage",
    "numeric_ids",
    "preserve_acls",
    "preserve_xattrs",
    "preserve_hardlinks",
    "rsync",
    "presets",
    "targets",
}

DEFAULT_CONFIG_TEXT = r"""# chronos config
# Default path: ~/.config/chronos/config.toml

backup_dir = "/mnt/storage/bak"
restore_root = "/"

# What -a / all means.
# home, boot, and efi are available as explicit targets, but not included by default.
all_targets = ["root"]

# Ask before restoring to the live running root filesystem.
confirm_restore_to_live_root = true

# Check that backup_dir is on a real mounted filesystem, not just a directory on /.
require_backup_mount = true

# Inspect source/destination filesystems and adjust rsync metadata flags when needed.
check_filesystems = true

# If a filesystem clearly cannot preserve ACLs/xattrs, skip unsupported rsync flags instead
# of failing with noisy filesystem errors. chronos will warn before doing this.
auto_disable_unsupported_metadata = true

# For SELinux systems, touch .autorelabel after root restore when appropriate.
# Values: "auto", true, false
touch_autorelabel = "auto"

# How to handle SELinux security.* xattrs when -X is enabled.
# Values:
#   "auto"     - exclude security.* from sender+receiver sides. This keeps other
#                xattrs, avoids rsync_xal_set/lremovexattr spam on backup disks,
#                and lets restore use .autorelabel for root labels.
#   "preserve" - require real SELinux label preservation; fail if unavailable.
#   "exclude"  - same as auto, but explicit.
selinux_xattrs = "auto"

# Global rsync behavior. Target-level values can override these.
delete = true
delete_excluded = true

# Home backups exclude rootless container storage by default. Podman overlay
# storage can contain shifted-ownership/protected files that spam Permission
# denied and often should be rebuilt, not restored as raw home files.
# Define a custom target for important container bind mounts/volumes if needed.
exclude_container_storage = true

numeric_ids = true
preserve_acls = true
preserve_xattrs = true
preserve_hardlinks = true

[rsync]
# Extra arguments appended to every backup/restore rsync call.
extra_backup_args = []
extra_restore_args = []

[presets]
# A preset can be selected like a target:
#   sudo chronos -b desktop
#   sudo chronos restore desktop
#
# [presets.desktop]
# targets = ["root", "home", "efi", "projects"]
#
# You may also make a preset mode-specific:
# [presets.fast]
# backup_targets = ["home", "projects"]
# restore_targets = ["home"]

[targets.root]
src = "/"
dst = "root"
requires_root = true
one_file_system = true
# /boot is intentionally not excluded here. If /boot is a separate mount,
# --one-file-system skips it. If /boot is just a directory on /, it is backed up.
backup_exclude = [
  "/home/***",
  "/efi/***",
  "/boot/efi/***",
  "/proc/***",
  "/sys/***",
  "/dev/***",
  "/run/***",
  "/tmp/***",
  "/var/tmp/***",
  "/var/cache/***",
  "/mnt/***",
  "/media/***",
  "/.snapshots/***",
  "/lost+found",
]
restore_exclude = [
  "/home/***",
  "/proc/***",
  "/sys/***",
  "/dev/***",
  "/run/***",
  "/tmp/***",
  "/mnt/***",
  "/media/***",
]
create_dirs_after_restore = [
  "proc", "sys", "dev", "run", "tmp", "mnt", "media", "home", "boot", "efi"
]

[targets.home]
src = "~/"
dst = "home"
requires_root = false
one_file_system = true
backup_exclude = [
  ".cache/***",
  ".local/share/Trash/***",
  ".local/share/containers/storage/***",
  ".local/share/containers/cache/***",
]
restore_exclude = []

[targets.efi]
# First mounted path wins.
src_candidates = ["/efi/", "/boot/efi/"]
dst = "efi"
requires_root = true
# ESP is usually FAT, so -A/-X are not useful here.
preserve_acls = false
preserve_xattrs = false
one_file_system = false
mount_required = true
backup_exclude = []
restore_exclude = []

[targets.boot]
src = "/boot/"
dst = "boot"
requires_root = true
one_file_system = true
backup_exclude = [
  "/efi/***",
]
restore_exclude = [
  "/efi/***",
]

# Example custom target:
# [targets.projects]
# src = "/mnt/data0/projects/"
# dst = "projects"
# requires_root = false  # custom targets default to user mode
# one_file_system = true
# versioned = true
# keep_versions = 10
# backup_exclude = ["*/target/***", "*/.git/***/objects/***"]
# restore_exclude = []
#
# Custom targets default to user mode. Set requires_root = true only when the
# source truly requires root privileges (for example, system paths). A path
# such as /mnt/data0/projects should not need sudo if your user can read it.
"""

DEFAULT_CONFIG: dict[str, Any] = {
    "backup_dir": "/mnt/storage/bak",
    "restore_root": "/",
    "all_targets": ["root"],
    "confirm_restore_to_live_root": True,
    "require_backup_mount": True,
    "check_filesystems": True,
    "auto_disable_unsupported_metadata": True,
    "touch_autorelabel": "auto",
    "selinux_xattrs": "auto",
    "delete": True,
    "delete_excluded": True,
    "exclude_container_storage": True,
    "numeric_ids": True,
    "preserve_acls": True,
    "preserve_xattrs": True,
    "preserve_hardlinks": True,
    "rsync": {
        "extra_backup_args": [],
        "extra_restore_args": [],
    },
    "presets": {},
    "targets": {
        "root": {
            "src": "/",
            "dst": "root",
            "requires_root": True,
            "one_file_system": True,
            "backup_exclude": [
                "/home/***",
                "/efi/***",
                "/boot/efi/***",
                "/proc/***",
                "/sys/***",
                "/dev/***",
                "/run/***",
                "/tmp/***",
                "/var/tmp/***",
                "/var/cache/***",
                "/mnt/***",
                "/media/***",
                "/.snapshots/***",
                "/lost+found",
            ],
            "restore_exclude": [
                "/home/***",
                "/proc/***",
                "/sys/***",
                "/dev/***",
                "/run/***",
                "/tmp/***",
                "/mnt/***",
                "/media/***",
            ],
            "create_dirs_after_restore": [
                "proc", "sys", "dev", "run", "tmp",
                "mnt", "media", "home", "boot", "efi",
            ],
        },
        "home": {
            "src": "~/",
            "dst": "home",
            "requires_root": False,
            "one_file_system": True,
            "backup_exclude": [
                ".cache/***",
                ".local/share/Trash/***",
                ".local/share/containers/storage/***",
                ".local/share/containers/cache/***",
            ],
            "restore_exclude": [],
        },
        "efi": {
            "src_candidates": ["/efi/", "/boot/efi/"],
            "dst": "efi",
            "requires_root": True,
            "preserve_acls": False,
            "preserve_xattrs": False,
            "one_file_system": False,
            "mount_required": True,
            "backup_exclude": [],
            "restore_exclude": [],
        },
        "boot": {
            "src": "/boot/",
            "dst": "boot",
            "requires_root": True,
            "one_file_system": True,
            "backup_exclude": ["/efi/***"],
            "restore_exclude": ["/efi/***"],
        },
    },
}

FILE_CONFIG_BASE: dict[str, Any] = deepcopy(DEFAULT_CONFIG)
FILE_CONFIG_BASE["all_targets"] = []
FILE_CONFIG_BASE["presets"] = {}
FILE_CONFIG_BASE["targets"] = {}


# ---------------------------------------------------------------------------
# User identity helpers
# ---------------------------------------------------------------------------

def original_user_name() -> str:
    """Return the real invoking user, even after sudo re-exec."""
    for key in ("CHRONOS_ORIGINAL_USER", "SUDO_USER", "USER", "LOGNAME"):
        value = os.environ.get(key)
        if value and value != "root":
            return value
    return pwd.getpwuid(os.getuid()).pw_name


def original_user_home() -> Path:
    """Return the real invoking user's home, not /root after sudo."""
    env_home = os.environ.get("CHRONOS_ORIGINAL_HOME")
    if env_home:
        return Path(env_home)

    sudo_uid = os.environ.get("SUDO_UID")
    if sudo_uid and sudo_uid.isdigit():
        try:
            return Path(pwd.getpwuid(int(sudo_uid)).pw_dir)
        except KeyError:
            pass

    user = os.environ.get("SUDO_USER") or os.environ.get("CHRONOS_ORIGINAL_USER")
    if user:
        try:
            return Path(pwd.getpwnam(user).pw_dir)
        except KeyError:
            pass

    return Path.home()


def default_config_path() -> Path:
    return original_user_home() / ".config" / "chronos" / "config.toml"


def user_config_dir() -> Path:
    return original_user_home() / ".config" / "chronos"


def expand_user_path(path: str | Path) -> Path:
    """Expand ~ using the original invoking user, not root after sudo."""
    text = str(path)
    if text == "~":
        return original_user_home()
    if text.startswith("~/"):
        return original_user_home() / text[2:]
    return Path(text).expanduser()


# ---------------------------------------------------------------------------
# Config file path discovery
# ---------------------------------------------------------------------------

def system_config_paths() -> list[Path]:
    paths: list[Path] = []
    if SYSTEM_CONFIG_PATH.exists():
        paths.append(SYSTEM_CONFIG_PATH)
    if SYSTEM_CONFIG_DROPIN_DIR.exists() and SYSTEM_CONFIG_DROPIN_DIR.is_dir():
        paths.extend(
            sorted(
                p
                for p in SYSTEM_CONFIG_DROPIN_DIR.glob("*.toml")
                if p.is_file() and not p.name.startswith(".")
            )
        )
    return paths


def user_config_paths() -> list[Path]:
    cfg_dir = user_config_dir()
    if not cfg_dir.exists() or not cfg_dir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(cfg_dir.glob("*.toml")):
        name = p.name
        if (
            name.startswith(".")
            or name.endswith(".bak")
            or name.endswith(".tmp")
            or name.endswith(".rpmnew")
            or name.endswith(".rpmsave")
        ):
            continue
        if p.is_file():
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Config merging
# ---------------------------------------------------------------------------

def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Config validation helpers
# ---------------------------------------------------------------------------

def config_error(config_path: Path | None, message: str) -> ChronosError:
    where = str(config_path) if config_path is not None else "default config"
    return ChronosError(f"invalid config ({where}): {message}")


def require_bool(
    config: dict[str, Any], key: str, config_path: Path | None, *, scope: str = ""
) -> bool:
    value = config.get(key)
    if not isinstance(value, bool):
        label = f"{scope}.{key}" if scope else key
        raise config_error(config_path, f"{label} must be a boolean")
    return value


def require_string(
    config: dict[str, Any],
    key: str,
    config_path: Path | None,
    *,
    scope: str = "",
    non_empty: bool = False,
) -> str:
    value = config.get(key)
    if not isinstance(value, str):
        label = f"{scope}.{key}" if scope else key
        raise config_error(config_path, f"{label} must be a string")
    if non_empty and not value.strip():
        label = f"{scope}.{key}" if scope else key
        raise config_error(config_path, f"{label} must be a non-empty string")
    return value


def require_table(
    config: dict[str, Any], key: str, config_path: Path | None, *, scope: str = ""
) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        label = f"{scope}.{key}" if scope else key
        raise config_error(config_path, f"{label} must be a table")
    return value


def require_string_list(
    config: dict[str, Any],
    key: str,
    config_path: Path | None,
    *,
    scope: str = "",
    non_empty: bool = False,
) -> list[str]:
    value = config.get(key)
    label = f"{scope}.{key}" if scope else key
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise config_error(config_path, f"{label} must be a list of strings")
    if non_empty and not value:
        raise config_error(config_path, f"{label} must be a non-empty list of strings")
    return value


def validate_targets(config: dict[str, Any], config_path: Path | None) -> None:
    targets = require_table(config, "targets", config_path)
    allowed_target_keys = {
        "src", "src_candidates", "dst",
        "backup_exclude", "restore_exclude", "create_dirs_after_restore",
        "one_file_system", "mount_required",
        "preserve_acls", "preserve_xattrs", "numeric_ids", "preserve_hardlinks",
        "delete", "delete_excluded",
        "requires_root", "versioned", "keep_versions",
    }
    bool_keys = {
        "one_file_system", "mount_required",
        "preserve_acls", "preserve_xattrs", "numeric_ids", "preserve_hardlinks",
        "delete", "delete_excluded", "requires_root", "versioned",
    }
    list_keys = {"backup_exclude", "restore_exclude", "create_dirs_after_restore"}

    for name, target in targets.items():
        if not isinstance(name, str) or not TARGET_NAME_RE.fullmatch(name):
            raise config_error(
                config_path, f"target name {name!r} must match [A-Za-z0-9_.-]+"
            )
        if name in RESERVED_TARGET_NAMES:
            raise config_error(config_path, f"target name {name!r} is reserved")
        if not isinstance(target, dict):
            raise config_error(config_path, f"targets.{name} must be a table")

        unknown_keys = sorted(set(target) - allowed_target_keys)
        if unknown_keys:
            raise config_error(
                config_path,
                f"targets.{name} has unknown key(s): {', '.join(unknown_keys)}",
            )

        has_src = "src" in target
        has_src_candidates = "src_candidates" in target
        if has_src == has_src_candidates:
            raise config_error(
                config_path,
                f"targets.{name} must define exactly one of src or src_candidates",
            )

        if has_src:
            require_string(target, "src", config_path, scope=f"targets.{name}", non_empty=True)
        if has_src_candidates:
            require_string_list(
                target, "src_candidates", config_path,
                scope=f"targets.{name}", non_empty=True,
            )

        require_string(target, "dst", config_path, scope=f"targets.{name}", non_empty=True)

        for key in list_keys & set(target):
            require_string_list(target, key, config_path, scope=f"targets.{name}")
        for key in bool_keys & set(target):
            require_bool(target, key, config_path, scope=f"targets.{name}")
        if "keep_versions" in target:
            value = target["keep_versions"]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise config_error(
                    config_path,
                    f"targets.{name}.keep_versions must be an integer >= 1",
                )
            if not target.get("versioned", False):
                raise config_error(
                    config_path,
                    f"targets.{name}.keep_versions requires versioned = true",
                )


def validate_presets(config: dict[str, Any], config_path: Path | None) -> None:
    presets = require_table(config, "presets", config_path)
    targets = require_table(config, "targets", config_path)

    for name, preset in presets.items():
        if not isinstance(name, str):
            raise config_error(config_path, "preset names must be strings")
        if not isinstance(preset, dict):
            raise config_error(config_path, f"presets.{name} must be a table")

        keys = ("targets", "backup_targets", "restore_targets")
        if not any(key in preset for key in keys):
            raise config_error(
                config_path,
                f"presets.{name} must define targets, backup_targets, or restore_targets",
            )

        for key in keys:
            if key not in preset:
                continue
            values = require_string_list(
                preset, key, config_path, scope=f"presets.{name}", non_empty=True
            )
            for target_name in values:
                normalized = normalize_builtin_selection(target_name)
                if normalized == "all":
                    continue
                if normalized not in targets:
                    raise config_error(
                        config_path,
                        f"presets.{name}.{key} references unknown target: {target_name}",
                    )


def validate_config(config: dict[str, Any], config_path: Path | None) -> dict[str, Any]:
    unknown_top = sorted(set(config) - ALLOWED_TOP_LEVEL_KEYS)
    if unknown_top:
        raise config_error(config_path, f"unknown top-level key(s): {', '.join(unknown_top)}")

    require_string(config, "backup_dir", config_path, non_empty=True)
    require_string(config, "restore_root", config_path, non_empty=True)
    require_string_list(config, "all_targets", config_path, non_empty=True)

    for key in (
        "confirm_restore_to_live_root", "require_backup_mount", "check_filesystems",
        "auto_disable_unsupported_metadata", "delete", "delete_excluded",
        "exclude_container_storage", "numeric_ids",
        "preserve_acls", "preserve_xattrs", "preserve_hardlinks",
    ):
        require_bool(config, key, config_path)

    rsync = require_table(config, "rsync", config_path)
    require_table(config, "presets", config_path)
    require_table(config, "targets", config_path)

    touch = config.get("touch_autorelabel")
    if touch not in {"auto", True, False}:
        raise config_error(config_path, 'touch_autorelabel must be "auto", true, or false')

    selinux_xattrs = config.get("selinux_xattrs")
    if selinux_xattrs not in {"auto", "preserve", "exclude"}:
        raise config_error(
            config_path, 'selinux_xattrs must be "auto", "preserve", or "exclude"'
        )

    require_string_list(rsync, "extra_backup_args", config_path, scope="rsync")
    require_string_list(rsync, "extra_restore_args", config_path, scope="rsync")

    validate_targets(config, config_path)

    for target_name in require_string_list(config, "all_targets", config_path, non_empty=True):
        normalized = normalize_builtin_selection(target_name)
        if normalized == "all":
            continue
        if normalized not in config["targets"]:
            raise config_error(
                config_path,
                f"all_targets references unknown target: {target_name}",
            )

    validate_presets(config, config_path)
    return config


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ChronosError(f"invalid TOML in config {path}: {exc}") from None
    except OSError as exc:
        raise ChronosError(f"cannot read config {path}: {exc}") from exc


def load_config(path: Path | None) -> tuple[dict[str, Any], Path | None]:
    if path is None:
        path = default_config_path()
        if not path.exists():
            return deepcopy(DEFAULT_CONFIG), None
        base_config = DEFAULT_CONFIG
    elif not path.exists():
        raise ChronosError(f"config file does not exist: {path}")
    else:
        base_config = FILE_CONFIG_BASE

    user_config = load_config_file(path)
    config = deep_merge(base_config, user_config)
    return validate_config(config, path), path


def load_merged_system_config() -> ConfigJob | None:
    paths = system_config_paths()
    if not paths:
        return None
    merged = deepcopy(FILE_CONFIG_BASE)
    for path in paths:
        merged = deep_merge(merged, load_config_file(path))
    validated = validate_config(
        merged,
        SYSTEM_CONFIG_PATH if SYSTEM_CONFIG_PATH.exists() else None,
    )
    return ConfigJob(
        path=SYSTEM_CONFIG_PATH if SYSTEM_CONFIG_PATH.exists() else None,
        scope="system",
        config=validated,
        display_name="system:/etc/chronos/config.toml",
    )


def load_user_config_jobs() -> list[ConfigJob]:
    jobs: list[ConfigJob] = []
    for path in user_config_paths():
        cfg = deep_merge(FILE_CONFIG_BASE, load_config_file(path))
        jobs.append(
            ConfigJob(
                path=path,
                scope="user",
                config=validate_config(cfg, path),
                display_name=f"user:{path}",
            )
        )
    return jobs


def write_default_config(path: Path | None = None) -> None:
    if path is None:
        path = default_config_path()
    if path.exists():
        raise ChronosError(f"config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    ok(f"created config: {path}")


# ---------------------------------------------------------------------------
# Target and preset selection
# ---------------------------------------------------------------------------

def normalize_builtin_selection(word: str) -> str:
    return TARGET_ALIASES.get(word, word)


def expand_preset(config: dict[str, Any], name: str, mode: str) -> list[str] | None:
    presets = config.get("presets", {})
    if name not in presets:
        return None
    preset = presets[name]
    if isinstance(preset, list):
        return [str(x) for x in preset]
    if isinstance(preset, dict):
        mode_key = f"{mode}_targets"
        if mode_key in preset:
            return [str(x) for x in preset[mode_key]]
        return [str(x) for x in preset.get("targets", [])]
    raise ChronosError(f"invalid preset format: {name}")


def selected_targets(config: dict[str, Any], plan: Plan) -> list[str]:
    if not plan.selections:
        raise ChronosError(
            "choose targets: -a, root, home, efi, boot, or a configured preset/target"
        )

    configured = config.get("targets", {})
    out: list[str] = []

    def append_target(target: str, stack: list[str]) -> None:
        normalized = normalize_builtin_selection(target)
        if normalized == "all":
            for t in config.get("all_targets", []):
                append_target(str(t), [*stack, "all"])
            return

        preset_targets = expand_preset(config, normalized, plan.mode)
        if preset_targets is not None:
            if normalized in stack:
                raise ChronosError(
                    f"recursive preset detected: {' -> '.join([*stack, normalized])}"
                )
            for t in preset_targets:
                append_target(t, [*stack, normalized])
            return

        if normalized not in configured:
            raise ChronosError(f"target or preset not configured: {target}")
        if normalized not in out:
            out.append(normalized)

    for selection in plan.selections:
        append_target(selection, [])

    return out


def job_targets(job: ConfigJob, plan: Plan) -> list[str]:
    effective = Plan(mode=plan.mode, selections=list(plan.selections))
    return selected_targets(job.config, effective)


def selected_job_targets(job: ConfigJob, plan: Plan) -> list[str]:
    if plan.selections:
        return job_targets(job, plan)
    return selected_targets(job.config, Plan(mode=plan.mode, selections=["all"]))


# ---------------------------------------------------------------------------
# Root requirement checks
# ---------------------------------------------------------------------------

def target_requires_root(target_config: dict[str, Any]) -> bool:
    return bool(target_config.get("requires_root", False))


def target_needs_root(config: dict[str, Any], target: str, mode: str) -> bool:  # noqa: ARG001
    return target_requires_root(config["targets"][target])


def needs_root(config: dict[str, Any], targets: list[str], mode: str) -> bool:
    return any(target_needs_root(config, t, mode) for t in targets)


# ---------------------------------------------------------------------------
# Config job discovery
# ---------------------------------------------------------------------------

def discover_config_jobs(plan: Plan) -> list[ConfigJob]:
    if plan.config_path is not None:
        config, _ = load_config(plan.config_path)
        return [
            ConfigJob(
                path=plan.config_path,
                scope="explicit",
                config=config,
                display_name=f"explicit:{plan.config_path}",
            )
        ]

    jobs: list[ConfigJob] = []
    system_job = load_merged_system_config()
    user_jobs = load_user_config_jobs()
    if plan.scope in {"auto", "system"} and system_job is not None:
        jobs.append(system_job)
    if plan.scope in {"auto", "user"}:
        jobs.extend(user_jobs)
    return jobs


def discover_config_jobs_for_run(plan: Plan) -> list[ConfigJob]:
    jobs = discover_config_jobs(plan)
    if not jobs:
        if plan.config_path is None and plan.scope == "auto":
            config, _ = load_config(None)
            return [ConfigJob(path=None, scope="builtin", config=config, display_name="builtin")]
        raise ChronosError("no matching config files were discovered")

    if plan.config_path is not None:
        return jobs
    if not plan.selections:
        return jobs
    if plan.selections == ["all"] or plan.all_configs:
        return jobs

    matches: list[ConfigJob] = []
    for job in jobs:
        try:
            selected = job_targets(job, plan)
        except ChronosError:
            continue
        if selected:
            matches.append(job)

    if not matches:
        raise ChronosError(f"target or preset not configured: {', '.join(plan.selections)}")
    if len(matches) > 1:
        names = ", ".join(job.display_name for job in matches)
        raise ChronosError(
            f"ambiguous target selection across multiple configs: {names}. "
            "use --scope or --config"
        )
    return matches


# ---------------------------------------------------------------------------
# Backup path helpers
# ---------------------------------------------------------------------------

def target_backup_root(
    config: dict[str, Any], target_config: dict[str, Any], *, target: str | None = None
) -> Path:
    backup_dir = expand_user_path(config["backup_dir"])
    dst_name = target_config.get("dst", target)
    if dst_name is None:
        raise ChronosError("target destination is not configured")
    dst = backup_dir / str(dst_name)
    if str(target_config.get("src", "")).startswith("~"):
        dst = dst / original_user_home().name
    return dst


def backup_dest(config: dict[str, Any], target: str) -> Path:
    return target_backup_root(config, config["targets"][target], target=target)


def extra_info_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("extra_info", False))
