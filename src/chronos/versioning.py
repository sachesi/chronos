from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import backup_dest
from .output import warn
from .types import ChronosError

VERSION_NAME_RE = re.compile(r"^[0-9]{8}-[0-9]{6}(?:-[0-9]+)?$")


def validate_version_name(name: str) -> str:
    if "/" in name or ".." in name:
        raise ChronosError(f"invalid version name: {name}")
    if not VERSION_NAME_RE.fullmatch(name):
        raise ChronosError(f"invalid version name: {name}")
    return name


def version_name_now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def is_target_versioned(target_config: dict[str, Any]) -> bool:
    return bool(target_config.get("versioned", False))


def target_versions_dir(config: dict[str, Any], target: str) -> Path:
    return backup_dest(config, target) / "versions"


def list_target_versions(config: dict[str, Any], target: str) -> list[str]:
    versions_dir = target_versions_dir(config, target)
    if not versions_dir.exists():
        return []
    if not versions_dir.is_dir():
        raise ChronosError(f"versions path is not a directory: {versions_dir}")
    return sorted(
        [
            p.name
            for p in versions_dir.iterdir()
            if p.is_dir() and VERSION_NAME_RE.fullmatch(p.name)
        ],
        reverse=True,
    )


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def resolve_current_version(config: dict[str, Any], target: str) -> Path | None:
    current = backup_dest(config, target) / "current"
    if not current.exists():
        return None
    if not current.is_symlink():
        raise ChronosError(f"current is not a symlink for target: {target}")

    versions_dir = target_versions_dir(config, target)
    resolved = current.resolve(strict=True)
    versions_real = versions_dir.resolve()
    if not is_relative_to(resolved, versions_real):
        raise ChronosError(f"current points outside versions directory for target: {target}")
    if not resolved.is_dir():
        raise ChronosError(f"current target is not a directory for target: {target}")
    return resolved


def create_version_dir(config: dict[str, Any], target: str) -> tuple[str, Path, Path]:
    target_root = backup_dest(config, target)
    versions_dir = target_versions_dir(config, target)
    target_root.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)

    base = version_name_now()
    candidate = base
    index = 1
    while True:
        final_dir = versions_dir / candidate
        incomplete_dir = target_root / f".incomplete-{candidate}"
        if not final_dir.exists() and not incomplete_dir.exists():
            incomplete_dir.mkdir(parents=True, exist_ok=False)
            return candidate, incomplete_dir, final_dir
        index += 1
        candidate = f"{base}-{index}"


def update_current_symlink(config: dict[str, Any], target: str, version_name: str) -> None:
    target_root = backup_dest(config, target)
    current = target_root / "current"
    versions_dir = target_versions_dir(config, target)
    version_dir = versions_dir / version_name
    if not version_dir.is_dir():
        raise ChronosError(f"missing completed version directory: {version_dir}")
    relative_target = Path("versions") / version_name
    if current.exists() or current.is_symlink():
        if not current.is_symlink():
            raise ChronosError(f"refusing to replace non-symlink current path: {current}")
        current.unlink()
    current.symlink_to(relative_target)


def prune_old_versions(config: dict[str, Any], target: str, keep: int) -> None:
    versions_dir = target_versions_dir(config, target)
    if not versions_dir.exists():
        return

    versions_real = versions_dir.resolve()
    current_target = resolve_current_version(config, target)
    versions = list_target_versions(config, target)
    to_remove = versions[keep:]

    for name in to_remove:
        version_path = versions_dir / name
        try:
            resolved = version_path.resolve(strict=True)
        except OSError:
            warn(f"skipping prune of unreadable version path: {version_path}")
            continue
        if not is_relative_to(resolved, versions_real):
            warn(f"skipping prune outside versions directory: {version_path}")
            continue
        if current_target is not None and resolved == current_target:
            continue
        if version_path.is_symlink():
            warn(f"skipping symlink in versions directory: {version_path}")
            continue
        shutil.rmtree(version_path)


def source_for_restore(
    config: dict[str, Any], target: str, requested_version: str | None
) -> Path:
    target_config = config["targets"][target]
    if not is_target_versioned(target_config):
        if requested_version is not None:
            raise ChronosError(
                f"--version cannot be used with non-versioned target: {target}"
            )
        return backup_dest(config, target)

    if requested_version is None:
        current = backup_dest(config, target) / "current"
        if not current.exists():
            raise ChronosError(f"missing current backup symlink: {current}")
        resolved = resolve_current_version(config, target)
        if resolved is None:
            raise ChronosError(f"missing current backup symlink: {current}")
        return current

    version = validate_version_name(requested_version)
    version_dir = target_versions_dir(config, target) / version
    if not version_dir.is_dir():
        raise ChronosError(f"missing backup version for {target}: {version}")
    return version_dir
