from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ChronosError(RuntimeError):
    pass


@dataclass
class Plan:
    mode: str = ""
    selections: list[str] = field(default_factory=list)
    list_versions_target: str | None = None
    version: str | None = None
    config_path: Path | None = None
    dry_run: bool = False
    yes: bool = False
    init_config: bool = False
    show_config: bool = False
    list_targets: bool = False
    backup_dir_override: str | None = None
    restore_root_override: str | None = None
    extra_info: bool | None = None
    scope: str = "auto"
    all_configs: bool = False
    list_configs: bool = False
    no_sudo: bool = False
    no_interactive: bool = False


@dataclass
class ConfigJob:
    path: Path | None
    scope: str
    config: dict[str, Any]
    display_name: str


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


@dataclass
class RSyncMessageStats:
    total: int = 0
    permission_denied: int = 0
    vanished: int = 0
    deletion_skipped: int = 0
    other: int = 0
    log_path: Path | None = None
