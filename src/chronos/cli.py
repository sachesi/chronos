from __future__ import annotations

import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import tomllib
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__

APP_NAME = "chronos"
INFO_GLYPH = "::"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "chronos" / "config.toml"

TARGET_ALIASES = {
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

NO_XATTR_FSTYPES = {
    "vfat",
    "msdos",
    "fat",
    "exfat",
    "ntfs",
    "ntfs3",
    "fuseblk",
    "iso9660",
    "udf",
}

NO_ACL_FSTYPES = {
    "vfat",
    "msdos",
    "fat",
    "exfat",
    "ntfs",
    "ntfs3",
    "fuseblk",
    "iso9660",
    "udf",
}

# Rsync xattr filter modifiers:
#   s = sender side, so source security.* xattrs are not copied.
#   r = receiver side, so destination security.* xattrs are protected from deletion.
# This avoids Fedora/SELinux rsync_xal_set lremovexattr spam while preserving user.* xattrs.
SELINUX_XATTR_FILTER_RULES = ["-xs security.*", "-xr security.*"]

# Rootless Podman/container storage often contains overlay layers with shifted
# ownership and protected files that a normal user cannot read. Backing it up as
# part of a generic home backup is noisy and usually not what users want; define
# dedicated targets for important bind-mounted volumes instead.
HOME_CONTAINER_EXCLUDES = [
    ".local/share/containers/storage/***",
    ".local/share/containers/cache/***",
]

DEFAULT_CONFIG_TEXT = r"""# chronos config
# Default path: ~/.config/chronos/config.toml

backup_dir = "/mnt/storage/bak"
restore_root = "/"

# What -a / all means.
# boot and efi are available as explicit targets, but not included by default.
all_targets = ["root", "home"]

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
progress = true
# Deprecated compatibility key. Prefer [ui].progress below.
progress_style = "chronos"

[ui]
# Values:
#   "chronos" - default compact one-line parser from rsync --info=progress2
#   "rsync"   - raw rsync --info=progress2 output
#   "none"    - no progress output
#   "auto"    - chronos on a TTY, none when redirected/logged
progress = "chronos"

# Show extra diagnostic details such as the full rsync command.
# Disabled by default to keep backup output readable.
extra-info = false

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
    "all_targets": ["root", "home"],
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
    "progress": True,
    "progress_style": "chronos",
    "ui": {
        "progress": "chronos",
        "extra-info": False,
    },
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
                "proc",
                "sys",
                "dev",
                "run",
                "tmp",
                "mnt",
                "media",
                "home",
                "boot",
                "efi",
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


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"


@dataclass
class Plan:
    mode: str = ""
    selections: list[str] = field(default_factory=list)
    config_path: Path | None = None
    dry_run: bool = False
    yes: bool = False
    init_config: bool = False
    show_config: bool = False
    list_targets: bool = False
    backup_dir_override: str | None = None
    restore_root_override: str | None = None
    extra_info: bool | None = None


@dataclass
class FilesystemInfo:
    path: Path
    target: str = ""
    source: str = ""
    fstype: str = "unknown"
    options: str = ""
    writable_xattr: bool | None = None

    def summary(self) -> str:
        src = f" from {self.source}" if self.source else ""
        return f"{self.fstype} mounted at {self.target or '?'}{src}"


@dataclass
class MetadataDecision:
    preserve_acls: bool
    preserve_xattrs: bool
    xattr_filter_rules: list[str] = field(default_factory=list)
    selinux_label_action: str = "not-requested"


@dataclass
class SELinuxInfo:
    present: bool
    enabled: bool
    enforcing: bool | None

    def summary(self) -> str:
        if not self.present:
            return "not detected"
        if not self.enabled:
            return "present, not mounted/enabled"
        if self.enforcing is True:
            return "enabled, enforcing"
        if self.enforcing is False:
            return "enabled, permissive"
        return "enabled"


class ChronosError(RuntimeError):
    pass


@dataclass
class RSyncMessageStats:
    total: int = 0
    permission_denied: int = 0
    vanished: int = 0
    deletion_skipped: int = 0
    other: int = 0
    log_path: Path | None = None


def use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(text: str, color: str) -> str:
    if not use_color():
        return text
    return f"{color}{text}{Color.RESET}"


def info(message: str) -> None:
    print(f"{c('::', Color.CYAN)} {message}")


def ok(message: str) -> None:
    print(f"{c('✓', Color.GREEN)} {message}")


def warn(message: str) -> None:
    print(f"{c('!', Color.YELLOW)} {message}")


def fail(message: str) -> None:
    print(f"{c('✗', Color.RED)} {message}", file=sys.stderr)


def section(title: str) -> None:
    width = shutil.get_terminal_size((88, 20)).columns
    label = f" {title} "
    line_len = max(0, width - len(label))
    print()
    print(c(label + "━" * line_len, Color.BOLD + Color.BLUE))


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def command_preview(argv: list[str]) -> str:
    return " ".join(shlex_quote(x) for x in argv)


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


def expand_user_path(path: str | Path) -> Path:
    """Expand ~ using the original invoking user, not root after sudo."""
    text = str(path)
    if text == "~":
        return original_user_home()
    if text.startswith("~/"):
        return original_user_home() / text[2:]
    return Path(text).expanduser()


def usage() -> str:
    return textwrap.dedent(
        f"""
        {APP_NAME} {__version__}

        Usage:
          chronos -ba                         Backup all configured targets
          chronos -b root -b home -b efi      Backup selected targets
          chronos -ra                         Restore all configured targets
          chronos -r root -r home -r efi      Restore selected targets

        Also works:
          chronos backup all
          chronos restore root home efi
          chronos -b desktop                  Backup a preset or custom target from config

        Options:
          -c, --config PATH           Use another config file
          -n, --dry-run               Show what rsync would do
          -y, --yes                   Do not ask restore confirmation
              --backup-dir PATH       Override backup_dir from config
              --restore-root PATH     Override restore_root from config
              --init-config           Create default ~/.config/chronos/config.toml
              --show-config           Print active config path and summary
              --list-targets          Show configured targets and presets
              --extra-info            Show verbose diagnostics, including rsync command
              --no-extra-info         Hide verbose diagnostics even if config enables them
          -h, --help                  Show help

        Default config path:
          {default_config_path()}
        """
    ).strip()


def normalize_builtin_selection(word: str) -> str:
    return TARGET_ALIASES.get(word, word)


def add_selection(plan: Plan, selection: str) -> None:
    normalized = normalize_builtin_selection(selection)
    if normalized not in plan.selections:
        plan.selections.append(normalized)


def set_mode(plan: Plan, mode: str) -> None:
    if plan.mode and plan.mode != mode:
        raise ChronosError("cannot combine backup and restore in one command")
    plan.mode = mode


def is_option_like(text: str) -> bool:
    return text.startswith("-") and text not in ("/", "/home", "/boot", "/efi", "/boot/efi")


def parse_args(argv: list[str]) -> Plan:
    plan = Plan()
    i = 0

    while i < len(argv):
        arg = argv[i]

        if arg in ("-h", "--help"):
            print(usage())
            raise SystemExit(0)
        if arg in ("--version", "version"):
            print(__version__)
            raise SystemExit(0)
        if arg in ("-c", "--config"):
            i += 1
            if i >= len(argv):
                raise ChronosError(f"{arg} needs a path")
            plan.config_path = expand_user_path(argv[i])
        elif arg.startswith("--config="):
            plan.config_path = expand_user_path(arg.split("=", 1)[1])
        elif arg == "--backup-dir":
            i += 1
            if i >= len(argv):
                raise ChronosError("--backup-dir needs a path")
            plan.backup_dir_override = argv[i]
        elif arg.startswith("--backup-dir="):
            plan.backup_dir_override = arg.split("=", 1)[1]
        elif arg == "--restore-root":
            i += 1
            if i >= len(argv):
                raise ChronosError("--restore-root needs a path")
            plan.restore_root_override = argv[i]
        elif arg.startswith("--restore-root="):
            plan.restore_root_override = arg.split("=", 1)[1]
        elif arg in ("-n", "--dry-run"):
            plan.dry_run = True
        elif arg in ("-y", "--yes"):
            plan.yes = True
        elif arg == "--init-config":
            plan.init_config = True
        elif arg == "--show-config":
            plan.show_config = True
        elif arg == "--list-targets":
            plan.list_targets = True
        elif arg == "--extra-info":
            plan.extra_info = True
        elif arg == "--no-extra-info":
            plan.extra_info = False
        elif arg in ("backup", "bak"):
            set_mode(plan, "backup")
        elif arg in ("restore", "rst"):
            set_mode(plan, "restore")
        elif arg in ("-b", "--backup"):
            set_mode(plan, "backup")
            if i + 1 < len(argv) and not is_option_like(argv[i + 1]):
                i += 1
                add_selection(plan, argv[i])
        elif arg in ("-r", "--restore"):
            set_mode(plan, "restore")
            if i + 1 < len(argv) and not is_option_like(argv[i + 1]):
                i += 1
                add_selection(plan, argv[i])
        elif arg.startswith("-") and not arg.startswith("--"):
            chars = arg[1:]
            for ch in chars:
                if ch == "b":
                    set_mode(plan, "backup")
                elif ch == "r":
                    set_mode(plan, "restore")
                elif ch == "a":
                    add_selection(plan, "all")
                elif ch == "n":
                    plan.dry_run = True
                elif ch == "y":
                    plan.yes = True
                elif ch == "h":
                    print(usage())
                    raise SystemExit(0)
                else:
                    raise ChronosError(f"unknown short option: -{ch}")
        elif not is_option_like(arg):
            add_selection(plan, arg)
        else:
            raise ChronosError(f"unknown argument: {arg}")

        i += 1

    return plan


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


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
    "progress",
    "progress_style",
    "ui",
    "rsync",
    "presets",
    "targets",
}


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
        "src",
        "src_candidates",
        "dst",
        "backup_exclude",
        "restore_exclude",
        "create_dirs_after_restore",
        "one_file_system",
        "mount_required",
        "preserve_acls",
        "preserve_xattrs",
        "numeric_ids",
        "preserve_hardlinks",
        "delete",
        "delete_excluded",
        "requires_root",
    }
    bool_keys = {
        "one_file_system",
        "mount_required",
        "preserve_acls",
        "preserve_xattrs",
        "numeric_ids",
        "preserve_hardlinks",
        "delete",
        "delete_excluded",
        "requires_root",
    }
    list_keys = {"backup_exclude", "restore_exclude", "create_dirs_after_restore"}

    for name, target in targets.items():
        if not isinstance(name, str) or not TARGET_NAME_RE.fullmatch(name):
            raise config_error(
                config_path,
                f"target name {name!r} must match [A-Za-z0-9_.-]+",
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
                target,
                "src_candidates",
                config_path,
                scope=f"targets.{name}",
                non_empty=True,
            )

        require_string(target, "dst", config_path, scope=f"targets.{name}", non_empty=True)

        for key in list_keys & set(target):
            require_string_list(target, key, config_path, scope=f"targets.{name}")
        for key in bool_keys & set(target):
            require_bool(target, key, config_path, scope=f"targets.{name}")


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
        "confirm_restore_to_live_root",
        "require_backup_mount",
        "check_filesystems",
        "auto_disable_unsupported_metadata",
        "delete",
        "delete_excluded",
        "exclude_container_storage",
        "numeric_ids",
        "preserve_acls",
        "preserve_xattrs",
        "preserve_hardlinks",
        "progress",
    ):
        require_bool(config, key, config_path)

    require_string(config, "progress_style", config_path, non_empty=True)
    ui = require_table(config, "ui", config_path)
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

    ui_progress = require_string(ui, "progress", config_path, scope="ui", non_empty=True)
    if ui_progress not in {"chronos", "rsync", "none", "auto"}:
        raise config_error(
            config_path, 'ui.progress must be "chronos", "rsync", "none", or "auto"'
        )
    require_bool(ui, "extra-info", config_path, scope="ui")

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


def load_config(path: Path | None) -> tuple[dict[str, Any], Path | None]:
    if path is None:
        path = default_config_path()
        if not path.exists():
            return deepcopy(DEFAULT_CONFIG), None
    elif not path.exists():
        raise ChronosError(f"config file does not exist: {path}")

    try:
        with path.open("rb") as f:
            user_config = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ChronosError(f"invalid TOML in config {path}: {exc}") from None
    except OSError as exc:
        raise ChronosError(f"cannot read config {path}: {exc}") from exc

    config = deep_merge(DEFAULT_CONFIG, user_config)
    return validate_config(config, path), path


def write_default_config(path: Path | None = None) -> None:
    if path is None:
        path = default_config_path()
    if path.exists():
        raise ChronosError(f"config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    ok(f"created config: {path}")


def target_needs_root(config: dict[str, Any], target: str, mode: str) -> bool:
    if mode == "restore":
        return True

    target_config = config["targets"][target]
    return target_requires_root(target_config)


def target_requires_root(target_config: dict[str, Any]) -> bool:
    return bool(target_config.get("requires_root", False))


def needs_root(config: dict[str, Any], targets: list[str], mode: str) -> bool:
    return any(target_needs_root(config, target, mode) for target in targets)


def config_arg_present(args: list[str]) -> bool:
    return "-c" in args or "--config" in args or any(a.startswith("--config=") for a in args)


def maybe_sudo_escalate(
    config: dict[str, Any],
    targets: list[str],
    mode: str,
    config_path: Path | None,
) -> None:
    """Re-exec through sudo only when the selected operation needs root."""
    if os.geteuid() == 0:
        return
    if not needs_root(config, targets, mode):
        return

    sudo = shutil.which("sudo")
    if sudo is None:
        raise ChronosError(
            "root privileges are required for selected targets, but sudo was not found"
        )

    args = sys.argv[1:]
    if config_path is not None and not config_arg_present(args):
        args = ["--config", str(config_path)] + args

    env_args = [
        f"CHRONOS_ORIGINAL_USER={original_user_name()}",
        f"CHRONOS_ORIGINAL_HOME={original_user_home()}",
    ]
    info("root privileges required for selected targets — re-running with sudo…")
    os.execvp(sudo, [sudo, *env_args, sys.argv[0], *args])


def run_capture(argv: list[str]) -> str:
    proc = subprocess.run(
        argv, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def is_mountpoint(path: str | Path) -> bool:
    return subprocess.run(["mountpoint", "-q", str(path)], check=False).returncode == 0


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise ChronosError(f"missing required command: {name}")


def ensure_backup_mount(backup_dir: Path, require_mount: bool) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not require_mount:
        return

    mount_target = run_capture(["findmnt", "-n", "-o", "TARGET", "--target", str(backup_dir)])
    if not mount_target or mount_target == "/":
        raise ChronosError(
            f"{backup_dir} is not on a mounted backup filesystem. "
            "Mount the backup disk or change backup_dir in config."
        )


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


def filesystem_info(path: str | Path) -> FilesystemInfo:
    p = expand_user_path(path)
    output = run_capture(["findmnt", "-n", "-T", str(p), "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"])
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
                # Either SELinux labels are not present on this mount, or policy hides them.
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


def selinux_xattr_policy(config: dict[str, Any]) -> str:
    value = str(config.get("selinux_xattrs", "auto")).lower()
    if value not in {"auto", "preserve", "exclude"}:
        raise ChronosError("selinux_xattrs must be one of: auto, preserve, exclude")
    return value


def fs_likely_supports_xattrs(fs: FilesystemInfo) -> bool:
    if fs.fstype in NO_XATTR_FSTYPES:
        return False
    return True


def fs_likely_supports_acls(fs: FilesystemInfo) -> bool:
    if fs.fstype in NO_ACL_FSTYPES:
        return False
    return True


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

    # A real write probe catches cases like unsupported xattrs on mounted network or FAT-like filesystems.
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
            # Do not merely exclude security.* from the sender. Existing backup files
            # often already have a security.selinux label assigned by the destination
            # filesystem. Without the receiver-side rule, rsync may try to
            # lremovexattr("security.selinux") and spam Permission denied.
            xattr_filter_rules.extend(SELINUX_XATTR_FILTER_RULES)
            selinux_label_action = (
                "excluded automatically" if policy == "auto" else "excluded by config"
            )
        else:
            can_manage = can_manage_selinux_xattr(dest_path)
            if can_manage:
                selinux_label_action = "preserved"
            else:
                message = (
                    "destination allows normal xattrs but does not allow managing "
                    "security.selinux labels; rsync -X would likely fail with code 23"
                )
                raise ChronosError(message)

    return MetadataDecision(
        preserve_acls=preserve_acls,
        preserve_xattrs=preserve_xattrs,
        xattr_filter_rules=xattr_filter_rules,
        selinux_label_action=selinux_label_action,
    )


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


def backup_dest(config: dict[str, Any], target: str) -> Path:
    backup_dir = expand_user_path(config["backup_dir"])
    target_config = config["targets"][target]
    dst = backup_dir / target_config.get("dst", target)
    if str(target_config.get("src", "")).startswith("~"):
        dst = dst / original_user_home().name
    return dst


def join_restore_root(restore_root: str | Path, subpath: str | Path) -> Path:
    root = expand_user_path(restore_root)
    sub = str(subpath)
    if sub.startswith("/"):
        sub = sub[1:]
    if str(root) == "/":
        return Path("/") / sub
    return root / sub


def configured_progress_style(config: dict[str, Any]) -> str:
    """Return the requested UI progress style.

    New configs should use [ui].progress. The old top-level progress_style key
    is still honored for compatibility with earlier Chronos builds.
    """
    ui = config.get("ui", {})
    if isinstance(ui, dict) and "progress" in ui:
        value = ui.get("progress", "chronos")
    else:
        value = config.get("progress_style", "chronos")

    style = str(value).strip().lower()
    aliases = {
        "": "chronos",
        "true": "chronos",
        "yes": "chronos",
        "on": "chronos",
        "false": "none",
        "no": "none",
        "off": "none",
        "quiet": "none",
        "raw": "rsync",
    }
    style = aliases.get(style, style)
    if style not in {"auto", "chronos", "rsync", "none"}:
        warn(f"unknown ui progress style {style!r}; using chronos")
        style = "chronos"
    return style


def effective_progress_style(config: dict[str, Any]) -> str:
    """Return the actual progress style for this process.

    Chronos' parser is useful only on an interactive TTY. When output is
    redirected or logged, the safe default is no progress output to avoid
    thousands of carriage-return progress lines in logs.
    """
    if not config.get("progress", True):
        return "none"

    requested = configured_progress_style(config)
    if requested == "auto":
        return "chronos" if sys.stdout.isatty() else "none"
    if requested == "chronos" and not sys.stdout.isatty():
        return "none"
    return requested


def extra_info_enabled(config: dict[str, Any]) -> bool:
    ui = config.get("ui", {})
    if isinstance(ui, dict):
        if "extra-info" in ui:
            return bool(ui.get("extra-info"))
        if "extra_info" in ui:
            return bool(ui.get("extra_info"))
    return bool(config.get("extra_info", False))


def build_rsync_args(
    config: dict[str, Any],
    target_config: dict[str, Any],
    *,
    mode: str,
    metadata: MetadataDecision,
) -> list[str]:
    args = ["rsync"]

    archive = "-a"
    if metadata.preserve_acls:
        archive += "A"
    if metadata.preserve_xattrs:
        archive += "X"
    if target_config.get("preserve_hardlinks", config.get("preserve_hardlinks", True)):
        archive += "H"
    args.append(archive)

    if config.get("numeric_ids", True):
        args.append("--numeric-ids")
    progress_style = effective_progress_style(config)
    if config.get("progress", True) and progress_style in {"rsync", "chronos"}:
        # progress2 gives whole-transfer progress. name0 avoids filename spam.
        args.append("--info=progress2,name0")
    if config.get("delete", True):
        args.append("--delete")
    if mode == "backup" and config.get("delete_excluded", True):
        args.append("--delete-excluded")
    if target_config.get("one_file_system", False):
        args.append("--one-file-system")

    for rule in metadata.xattr_filter_rules:
        args.append(f"--filter={rule}")

    extra_key = "extra_backup_args" if mode == "backup" else "extra_restore_args"
    args.extend(str(x) for x in config.get("rsync", {}).get(extra_key, []))
    return args


def append_excludes(args: list[str], patterns: list[str]) -> None:
    for pattern in patterns:
        args.append(f"--exclude={pattern}")


def choose_source(target: str, target_config: dict[str, Any]) -> Path:
    if "src_candidates" in target_config:
        for candidate in target_config["src_candidates"]:
            p = expand_user_path(candidate)
            if p.exists() and is_mountpoint(p):
                return p
        candidates = ", ".join(target_config["src_candidates"])
        raise ChronosError(f"no mounted source found for {target}; checked: {candidates}")

    src = expand_user_path(target_config["src"])
    if target_config.get("mount_required", False) and not is_mountpoint(src):
        raise ChronosError(f"{src} is not mounted")
    if not src.exists():
        raise ChronosError(f"source does not exist: {src}")
    return src


def ensure_trailing_slash(path: Path) -> str:
    text = str(path)
    return text if text.endswith("/") else text + "/"


def rsync_log_dir() -> Path:
    return original_user_home() / ".cache" / "chronos" / "logs"


def new_rsync_log_path() -> Path:
    log_dir = rsync_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return log_dir / f"rsync-{stamp}-{os.getpid()}.log"


def is_rsync_error_line(text: str) -> bool:
    return (
        text.startswith("rsync:")
        or text.startswith("IO error encountered")
        or text.startswith("rsync error:")
    )


def update_rsync_stats(stats: RSyncMessageStats, text: str) -> None:
    stats.total += 1
    lowered = text.lower()
    if "permission denied" in lowered:
        stats.permission_denied += 1
    elif "vanished" in lowered:
        stats.vanished += 1
    elif "skipping file deletion" in lowered:
        stats.deletion_skipped += 1
    else:
        stats.other += 1


def print_rsync_summary(stats: RSyncMessageStats) -> None:
    if stats.total == 0:
        return
    parts = []
    if stats.permission_denied:
        parts.append(f"{stats.permission_denied} permission-denied")
    if stats.vanished:
        parts.append(f"{stats.vanished} vanished")
    if stats.deletion_skipped:
        parts.append(f"{stats.deletion_skipped} deletion-skipped")
    if stats.other:
        parts.append(f"{stats.other} other")
    detail = ", ".join(parts) if parts else f"{stats.total} messages"
    warn(f"rsync reported {detail}; full log: {stats.log_path}")
    if stats.permission_denied:
        warn(
            "permission-denied files were skipped; for home backups this is often "
            "rootless container/overlay storage. Keep the default container-storage "
            "exclude or create a dedicated target for important bind-mounted data."
        )


PROGRESS_RE = re.compile(
    r"^\s*"
    r"(?P<transferred>[0-9][0-9,\.]*\s*[KMGTPE]?B?)\s+"
    r"(?P<percent>[0-9]{1,3})%\s+"
    r"(?P<rate>\S+)\s+"
    r"(?P<eta>\S+)"
    r"(?:\s+\((?P<details>[^)]*)\))?"
)


def terminal_width(default: int = 88) -> int:
    return shutil.get_terminal_size((default, 20)).columns


def render_progress(
    percent: int, transferred: str, rate: str, eta: str, details: str = "", warnings: int = 0
) -> str:
    # Keep progress intentionally plain and compact. Rsync already gives useful
    # whole-transfer fields via --info=progress2; reformat them without adding
    # a fake visual bar that cannot be accurate while rsync is still scanning.
    detail = f"  {details}" if details else ""
    prefix = c(INFO_GLYPH, Color.CYAN)
    return f"{prefix} {percent:3d}%  {transferred.strip():>12}  {rate:<12} eta {eta}{detail}"


def classify_rsync_line(line: str) -> tuple[str, re.Match[str] | None]:
    """Classify one rsync output fragment.

    rsync progress2 updates are carriage-return based and can arrive without a
    normal newline. We parse them into one Chronos progress line. Real warnings
    and errors are returned as messages so they remain visible.
    """
    text = line.strip()
    if not text:
        return "empty", None

    match = PROGRESS_RE.match(text)
    if match:
        return "progress", match

    # Lines that are just progress/check counters but did not match exactly
    # should not spam the terminal.
    if "to-chk=" in text or "ir-chk=" in text or "xfr#" in text:
        return "progress-no-match", None

    return "message", None


def run_rsync(
    args: list[str], *, dry_run: bool, progress_style: str = "chronos", show_command: bool = False
) -> None:
    if dry_run:
        args = [*args[:1], "--dry-run", *args[1:]]
    if show_command or dry_run:
        info(c(command_preview(args), Color.DIM))

    if progress_style != "chronos" or dry_run:
        proc = subprocess.run(args, check=False)
        if proc.returncode != 0:
            raise ChronosError(f"rsync failed with exit code {proc.returncode}")
        return

    stats = RSyncMessageStats(log_path=new_rsync_log_path())
    if stats.log_path is None:
        stats.log_path = new_rsync_log_path()

    log_file = stats.log_path.open("a", encoding="utf-8", errors="replace")
    log_file.write("$ " + command_preview(args) + "\n\n")
    log_file.flush()

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None

    last_progress = ""
    pending = ""
    last_render = 0.0

    def clear_progress_line() -> None:
        nonlocal last_progress
        if last_progress:
            print("\r" + " " * (terminal_width() - 1) + "\r", end="", flush=True)
            last_progress = ""

    def render_match(match: re.Match[str], *, force: bool = False) -> None:
        nonlocal last_progress, last_render
        now = time.monotonic()
        if not force and now - last_render < 0.08:
            return
        groups = match.groupdict()
        percent = max(0, min(100, int(groups["percent"])))
        last_progress = render_progress(
            percent,
            groups["transferred"],
            groups["rate"],
            groups["eta"],
            groups.get("details") or "",
            warnings=stats.total,
        )
        print("\r" + last_progress, end="", flush=True)
        last_render = now

    def handle_fragment(fragment: str, *, force: bool = False) -> None:
        text = fragment.strip()
        if not text:
            return

        kind, match = classify_rsync_line(text)
        if kind == "progress" and match is not None:
            render_match(match, force=force)
            return
        if kind == "progress-no-match":
            return

        # In Chronos progress mode, do not interleave every rsync warning with
        # the progress bar. It makes the UI unreadable on backups with many
        # permission-denied paths. Save messages to a log and summarize them.
        update_rsync_stats(stats, text)
        log_file.write(text + "\n")
        log_file.flush()

        # Non-rsync informational messages are rare; keep them visible.
        if not is_rsync_error_line(text):
            clear_progress_line()
            print(text)

    try:
        while True:
            ch = proc.stdout.read(1)
            if ch == "" and proc.poll() is not None:
                break
            if ch == "":
                continue
            if ch in "\r\n":
                fragment = pending
                pending = ""
                handle_fragment(fragment, force=(ch == "\n"))
            else:
                pending += ch

        if pending:
            handle_fragment(pending, force=True)

        rc = proc.wait()
        if last_progress:
            print()
        print_rsync_summary(stats)
        if rc != 0:
            message = f"rsync failed with exit code {rc}"
            if stats.log_path:
                message += f"; see {stats.log_path}"
            raise ChronosError(message)
    finally:
        log_file.close()


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
            "SELinux/security.* xattrs are excluded for this target, but other xattrs are still preserved; "
            "root restores will use .autorelabel to regenerate labels"
        )


def backup_excludes_for_target(
    config: dict[str, Any], target: str, target_config: dict[str, Any]
) -> list[str]:
    patterns = [str(x) for x in target_config.get("backup_exclude", [])]
    if target == "home" and config.get("exclude_container_storage", True):
        for pattern in HOME_CONTAINER_EXCLUDES:
            if pattern not in patterns:
                patterns.append(pattern)
    return patterns


def backup_target(
    config: dict[str, Any], target: str, *, dry_run: bool, selinux: SELinuxInfo
) -> None:
    target_config = config["targets"][target]
    src = choose_source(target, target_config)
    dst = backup_dest(config, target)
    dst.mkdir(parents=True, exist_ok=True)

    section(f"backup {target}")
    info(f"source:      {src}")
    info(f"destination: {dst}")

    source_fs = filesystem_info(src)
    dest_fs = filesystem_info(dst)
    info(f"source fs:   {source_fs.summary()}")
    info(f"dest fs:     {dest_fs.summary()}")

    metadata = decide_metadata(
        config, target_config, source_fs, dest_fs, dest_path=dst, mode="backup", selinux=selinux
    )
    show_extra_info = extra_info_enabled(config)
    if (
        show_extra_info
        and metadata.preserve_xattrs
        and selinux.present
        and target in ("root", "home")
    ):
        info(f"SELinux xattrs: {metadata.selinux_label_action}")
    warn_selinux_metadata_loss(selinux, target, metadata, show=show_extra_info)

    args = build_rsync_args(config, target_config, mode="backup", metadata=metadata)
    append_excludes(args, backup_excludes_for_target(config, target, target_config))
    args.extend([ensure_trailing_slash(src), ensure_trailing_slash(dst)])
    run_rsync(
        args,
        dry_run=dry_run,
        progress_style=effective_progress_style(config),
        show_command=extra_info_enabled(config),
    )
    ok(f"backup finished: {target}")


def efi_restore_destination(config: dict[str, Any]) -> Path:
    restore_root = expand_user_path(config["restore_root"])
    candidates = [
        join_restore_root(restore_root, "efi"),
        join_restore_root(restore_root, "boot/efi"),
    ]

    for candidate in candidates:
        if candidate.exists() and is_mountpoint(candidate):
            return candidate

    fallback = candidates[0]
    fallback.mkdir(parents=True, exist_ok=True)
    if not is_mountpoint(fallback):
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


def restore_target(
    config: dict[str, Any], target: str, *, dry_run: bool, selinux: SELinuxInfo
) -> None:
    target_config = config["targets"][target]
    src = backup_dest(config, target)
    if not src.exists():
        raise ChronosError(f"missing backup: {src}")
    dst = restore_destination(config, target)
    dst.mkdir(parents=True, exist_ok=True)
    create_restore_dirs(config, target)

    section(f"restore {target}")
    info(f"source:      {src}")
    info(f"destination: {dst}")

    source_fs = filesystem_info(src)
    dest_fs = filesystem_info(dst)
    info(f"source fs:   {source_fs.summary()}")
    info(f"dest fs:     {dest_fs.summary()}")

    metadata = decide_metadata(
        config, target_config, source_fs, dest_fs, dest_path=dst, mode="restore", selinux=selinux
    )
    show_extra_info = extra_info_enabled(config)
    if (
        show_extra_info
        and metadata.preserve_xattrs
        and selinux.present
        and target in ("root", "home")
    ):
        info(f"SELinux xattrs: {metadata.selinux_label_action}")
    warn_selinux_metadata_loss(selinux, target, metadata, show=show_extra_info)

    args = build_rsync_args(config, target_config, mode="restore", metadata=metadata)
    append_excludes(args, target_config.get("restore_exclude", []))
    args.extend([ensure_trailing_slash(src), ensure_trailing_slash(dst)])
    run_rsync(
        args,
        dry_run=dry_run,
        progress_style=effective_progress_style(config),
        show_command=extra_info_enabled(config),
    )

    if target == "root" and should_touch_autorelabel(config, selinux):
        try:
            join_restore_root(config["restore_root"], ".autorelabel").touch(exist_ok=True)
            ok("created .autorelabel for SELinux relabel on next boot")
        except OSError:
            warn("could not create .autorelabel")

    ok(f"restore finished: {target}")


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
    answer = input("Type RESTORE to continue: ").strip()
    if answer != "RESTORE":
        raise ChronosError("restore cancelled")


def print_summary(
    config: dict[str, Any],
    config_path: Path | None,
    targets: list[str] | None = None,
    selinux: SELinuxInfo | None = None,
) -> None:
    section("chronos")
    print(f"{c('version:', Color.BOLD)}      {__version__}")
    print(
        f"{c('config:', Color.BOLD)}       {config_path if config_path else '(built-in defaults)'}"
    )
    print(f"{c('backup dir:', Color.BOLD)}   {config['backup_dir']}")
    print(f"{c('restore root:', Color.BOLD)} {config['restore_root']}")
    print(f"{c('all targets:', Color.BOLD)}  {', '.join(config.get('all_targets', []))}")
    if selinux is not None:
        print(f"{c('SELinux:', Color.BOLD)}      {selinux.summary()}")
    if targets is not None:
        print(f"{c('selected:', Color.BOLD)}     {', '.join(targets)}")


def list_targets(config: dict[str, Any]) -> None:
    section("targets")
    for name, target in config.get("targets", {}).items():
        src = target.get("src") or ", ".join(target.get("src_candidates", []))
        in_all = name in config.get("all_targets", [])
        marker = c("*", Color.GREEN) if in_all else " "
        print(f" {marker} {c(name, Color.BOLD):<20} {src:<30} -> {backup_dest(config, name)}")
    print()
    print("* = included in -a / all")

    presets = config.get("presets", {})
    if presets:
        section("presets")
        for name, preset in presets.items():
            if isinstance(preset, list):
                desc = ", ".join(str(x) for x in preset)
            elif isinstance(preset, dict):
                parts = []
                if "targets" in preset:
                    parts.append("targets=" + ",".join(str(x) for x in preset["targets"]))
                if "backup_targets" in preset:
                    parts.append("backup=" + ",".join(str(x) for x in preset["backup_targets"]))
                if "restore_targets" in preset:
                    parts.append("restore=" + ",".join(str(x) for x in preset["restore_targets"]))
                desc = "  ".join(parts)
            else:
                desc = "invalid"
            print(f"   {c(name, Color.BOLD):<20} {desc}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    try:
        plan = parse_args(argv)

        if plan.init_config:
            write_default_config(plan.config_path)
            return 0

        config, config_path = load_config(plan.config_path)

        if plan.backup_dir_override:
            config["backup_dir"] = plan.backup_dir_override
        if plan.restore_root_override:
            config["restore_root"] = plan.restore_root_override
        if plan.extra_info is not None:
            config.setdefault("ui", {})["extra-info"] = plan.extra_info
        if plan.dry_run:
            warn("dry-run enabled")

        selinux = selinux_info()

        if plan.show_config:
            print_summary(config, config_path, selinux=selinux)
            return 0
        if plan.list_targets:
            print_summary(config, config_path, selinux=selinux)
            list_targets(config)
            return 0

        if not plan.mode:
            print(usage())
            return 2

        targets = selected_targets(config, plan)

        maybe_sudo_escalate(config, targets, plan.mode, config_path)
        print_summary(config, config_path, targets, selinux=selinux)

        require_tool("rsync")
        require_tool("findmnt")
        require_tool("mountpoint")
        ensure_backup_mount(
            expand_user_path(config["backup_dir"]), config.get("require_backup_mount", True)
        )
        confirm_restore(config, plan, targets)

        for target in targets:
            if plan.mode == "backup":
                backup_target(config, target, dry_run=plan.dry_run, selinux=selinux)
            else:
                restore_target(config, target, dry_run=plan.dry_run, selinux=selinux)

        section("done")
        ok("all selected operations completed")
        return 0

    except KeyboardInterrupt:
        fail("interrupted")
        return 130
    except ChronosError as e:
        fail(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
