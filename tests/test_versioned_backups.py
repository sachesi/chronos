from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronos.cli import (
    ChronosError,
    DEFAULT_CONFIG,
    backup_target,
    create_version_dir,
    deep_merge,
    list_target_versions,
    load_config,
    parse_args,
    prune_old_versions,
    resolve_current_version,
    selinux_info,
    source_for_restore,
    validate_plan,
    validate_version_name,
)


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_config_accepts_versioned_with_keep_versions(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path / "config.toml",
        """
[targets.projects]
src = "/mnt/data0/projects/"
dst = "projects"
versioned = true
keep_versions = 10
backup_exclude = []
restore_exclude = []
""",
    )

    config, _ = load_config(cfg)
    assert config["targets"]["projects"]["versioned"] is True
    assert config["targets"]["projects"]["keep_versions"] == 10


def test_versioned_must_be_bool(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path / "config.toml",
        """
[targets.projects]
src = "/mnt/data0/projects/"
dst = "projects"
versioned = "yes"
""",
    )

    with pytest.raises(ChronosError, match=r"targets\.projects\.versioned must be a boolean"):
        load_config(cfg)


def test_keep_versions_must_be_positive_int(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path / "config.toml",
        """
[targets.projects]
src = "/mnt/data0/projects/"
dst = "projects"
versioned = true
keep_versions = 0
""",
    )

    with pytest.raises(ChronosError, match=r"keep_versions must be an integer >= 1"):
        load_config(cfg)


def test_keep_versions_without_versioned_fails(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path / "config.toml",
        """
[targets.projects]
src = "/mnt/data0/projects/"
dst = "projects"
keep_versions = 10
""",
    )

    with pytest.raises(ChronosError, match=r"keep_versions requires versioned = true"):
        load_config(cfg)


@pytest.mark.parametrize("name", ["../bad", "bad/name", "not-a-timestamp"])
def test_version_name_validation_rejects_invalid(name: str) -> None:
    with pytest.raises(ChronosError, match=r"invalid version name"):
        validate_version_name(name)


def test_backup_path_for_versioned_target_uses_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "backup_dir": str(tmp_path),
            "targets": {
                "projects": {
                    "src": "/mnt/data0/projects/",
                    "dst": "projects",
                    "versioned": True,
                    "keep_versions": 10,
                }
            },
        },
    )
    monkeypatch.setattr("chronos.cli.version_name_now", lambda: "20260424-213001")

    version, incomplete, final_dir = create_version_dir(config, "projects")

    assert version == "20260424-213001"
    assert incomplete == tmp_path / "projects" / ".incomplete-20260424-213001"
    assert final_dir == tmp_path / "projects" / "versions" / "20260424-213001"


def test_restore_path_for_versioned_defaults_to_current(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    versions = root / "projects" / "versions"
    v1 = versions / "20260424-213001"
    v1.mkdir(parents=True)
    current = root / "projects" / "current"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.symlink_to(Path("versions") / v1.name)

    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "backup_dir": str(root),
            "targets": {
                "projects": {
                    "src": "/mnt/data0/projects/",
                    "dst": "projects",
                    "versioned": True,
                }
            },
        },
    )

    assert source_for_restore(config, "projects", None) == current


def test_restore_with_version_uses_selected_version(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    versions = root / "projects" / "versions"
    v1 = versions / "20260424-213001"
    v1.mkdir(parents=True)

    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "backup_dir": str(root),
            "targets": {
                "projects": {
                    "src": "/mnt/data0/projects/",
                    "dst": "projects",
                    "versioned": True,
                }
            },
        },
    )

    assert source_for_restore(config, "projects", "20260424-213001") == v1


def test_version_with_multiple_targets_fails_cleanly() -> None:
    plan = parse_args(["-r", "root", "-r", "home", "--version", "20260424-213001"])
    with pytest.raises(ChronosError, match=r"exactly one restore target"):
        validate_plan(plan)


def test_pruning_keeps_latest_n_and_never_deletes_current(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    versions = root / "projects" / "versions"
    versions.mkdir(parents=True)
    for name in ["20260424-120000", "20260424-130000", "20260424-140000"]:
        (versions / name).mkdir()

    current = root / "projects" / "current"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.symlink_to(Path("versions") / "20260424-120000")

    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "backup_dir": str(root),
            "targets": {
                "projects": {
                    "src": "/mnt/data0/projects/",
                    "dst": "projects",
                    "versioned": True,
                }
            },
        },
    )

    prune_old_versions(config, "projects", keep=1)

    assert (versions / "20260424-120000").exists()
    assert (versions / "20260424-140000").exists()
    assert not (versions / "20260424-130000").exists()


def test_pruning_ignores_non_matching_directories(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    versions = root / "projects" / "versions"
    versions.mkdir(parents=True)
    (versions / "20260424-120000").mkdir()
    (versions / "notes").mkdir()

    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "backup_dir": str(root),
            "targets": {
                "projects": {
                    "src": "/mnt/data0/projects/",
                    "dst": "projects",
                    "versioned": True,
                }
            },
        },
    )

    prune_old_versions(config, "projects", keep=1)

    assert (versions / "notes").exists()
    assert list_target_versions(config, "projects") == ["20260424-120000"]


def test_current_symlink_must_resolve_inside_versions_dir(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    (root / "outside").mkdir(parents=True)
    current = root / "projects" / "current"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.symlink_to(root / "outside")

    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "backup_dir": str(root),
            "targets": {
                "projects": {
                    "src": "/mnt/data0/projects/",
                    "dst": "projects",
                    "versioned": True,
                }
            },
        },
    )

    with pytest.raises(ChronosError, match=r"outside versions directory"):
        resolve_current_version(config, "projects")


def test_non_versioned_target_restore_behavior_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    home = root / "home"
    home.mkdir(parents=True)

    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "backup_dir": str(root),
            "targets": {
                "home": {
                    "src": "/home/test/",
                    "dst": "home",
                    "versioned": False,
                }
            },
        },
    )

    assert source_for_restore(config, "home", None) == home


def test_version_on_non_versioned_target_raises(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    home = root / "home"
    home.mkdir(parents=True)

    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "backup_dir": str(root),
            "targets": {
                "home": {
                    "src": "/home/test/",
                    "dst": "home",
                    "versioned": False,
                }
            },
        },
    )

    with pytest.raises(ChronosError, match=r"non-versioned target"):
        source_for_restore(config, "home", "20260424-213001")


def test_failed_versioned_backup_cleans_incomplete_and_does_not_update_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "backup"
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("data")

    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "backup_dir": str(root),
            "require_backup_mount": False,
            "check_filesystems": False,
            "progress": False,
            "targets": {
                "projects": {
                    "src": str(src) + "/",
                    "dst": "projects",
                    "requires_root": False,
                    "versioned": True,
                    "keep_versions": 10,
                    "backup_exclude": [],
                    "restore_exclude": [],
                }
            },
        },
    )
    monkeypatch.setattr("chronos.cli.version_name_now", lambda: "20260424-213001")
    monkeypatch.setattr("chronos.cli.run_rsync", lambda *a, **kw: (_ for _ in ()).throw(ChronosError("rsync failed")))

    selinux = selinux_info()
    with pytest.raises(ChronosError, match="rsync failed"):
        backup_target(config, "projects", dry_run=False, selinux=selinux)

    # incomplete dir must be removed
    assert not (root / "projects" / ".incomplete-20260424-213001").exists()
    # current must not have been created
    assert not (root / "projects" / "current").exists()
    # versions dir must be empty (or not exist)
    versions = root / "projects" / "versions"
    if versions.exists():
        assert list(versions.iterdir()) == []
