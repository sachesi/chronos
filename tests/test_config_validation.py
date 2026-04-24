from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronos.cli import ChronosError, DEFAULT_CONFIG, deep_merge, load_config, target_needs_root


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_invalid_toml_raises_clean_chronos_error(tmp_path: Path) -> None:
    cfg = write_config(tmp_path / "config.toml", 'all_targets = ["root",\n')

    with pytest.raises(ChronosError, match=r"invalid TOML in config"):
        load_config(cfg)


def test_custom_target_outside_home_is_valid_and_in_all_targets(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path / "config.toml",
        """
all_targets = ["efi", "root", "home", "projects"]

[targets.projects]
src = "/mnt/data0/projects/"
dst = "projects"
one_file_system = true
backup_exclude = ["*/target/***", "*/.git/***/objects/***"]
restore_exclude = []
""",
    )

    config, config_path = load_config(cfg)

    assert config_path == cfg
    assert "projects" in config["targets"]
    assert config["all_targets"] == ["efi", "root", "home", "projects"]


def test_all_targets_unknown_target_fails_cleanly(tmp_path: Path) -> None:
    cfg = write_config(tmp_path / "config.toml", 'all_targets = ["root", "project"]\n')

    with pytest.raises(
        ChronosError,
        match=r"invalid config .*all_targets references unknown target: project",
    ):
        load_config(cfg)


def test_preset_unknown_target_fails_cleanly(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path / "config.toml",
        """
[presets.work]
targets = ["home", "project"]
""",
    )

    with pytest.raises(
        ChronosError,
        match=r"invalid config .*presets\.work\.targets references unknown target: project",
    ):
        load_config(cfg)


def test_bad_ui_progress_fails_cleanly(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path / "config.toml",
        """
[ui]
progress = "fancy"
extra-info = false
""",
    )

    with pytest.raises(
        ChronosError,
        match=r'ui\.progress must be "chronos", "rsync", "none", or "auto"',
    ):
        load_config(cfg)


def test_target_with_both_src_and_src_candidates_fails(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path / "config.toml",
        """
[targets.projects]
src = "/mnt/data0/projects/"
src_candidates = ["/mnt/data0/projects/"]
dst = "projects"
""",
    )

    with pytest.raises(
        ChronosError,
        match=r"targets\.projects must define exactly one of src or src_candidates",
    ):
        load_config(cfg)


def test_target_with_neither_src_nor_src_candidates_fails(tmp_path: Path) -> None:
    cfg = write_config(
        tmp_path / "config.toml",
        """
[targets.projects]
dst = "projects"
""",
    )

    with pytest.raises(
        ChronosError,
        match=r"targets\.projects must define exactly one of src or src_candidates",
    ):
        load_config(cfg)


def test_custom_target_outside_home_does_not_require_root_by_default() -> None:
    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "targets": {
                "projects": {
                    "src": "/mnt/data0/projects/",
                    "dst": "projects",
                }
            }
        },
    )

    assert target_needs_root(config, "projects", "backup") is False


def test_custom_target_requires_root_false_does_not_require_root() -> None:
    config = deep_merge(
        DEFAULT_CONFIG,
        {
            "targets": {
                "projects": {
                    "src": "/mnt/data0/projects/",
                    "dst": "projects",
                    "requires_root": False,
                }
            }
        },
    )

    assert target_needs_root(config, "projects", "backup") is False


def test_builtin_system_targets_still_require_root_for_backup() -> None:
    assert target_needs_root(DEFAULT_CONFIG, "root", "backup") is True
    assert target_needs_root(DEFAULT_CONFIG, "efi", "backup") is True
    assert target_needs_root(DEFAULT_CONFIG, "boot", "backup") is True
    assert target_needs_root(DEFAULT_CONFIG, "home", "backup") is False
