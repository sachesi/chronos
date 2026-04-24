from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
import pytest

from chronos.cli import print_list_targets
from chronos.config import (
    discover_config_jobs_for_run,
    load_config,
    load_merged_system_config,
    load_user_config_jobs,
)
from chronos.types import Plan


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n")


def _user_target_config(name: str) -> str:
    return f"""
backup_dir = "/mnt/storage/bak"
restore_root = "/"
all_targets = ["{name}"]

[targets.{name}]
src = "/mnt/data0/{name}/"
dst = "{name}"
requires_root = false
"""


def _system_root_config() -> str:
    return """
backup_dir = "/mnt/storage/bak"
restore_root = "/"
all_targets = ["root"]

[targets.root]
src = "/"
dst = "root"
requires_root = true
"""


def test_user_config_does_not_inherit_builtin_targets(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write(home / ".config/chronos/projects.toml", _user_target_config("projects"))
    monkeypatch.setenv("CHRONOS_ORIGINAL_HOME", str(home))

    jobs = load_user_config_jobs()
    assert len(jobs) == 1
    assert set(jobs[0].config["targets"]) == {"projects"}
    assert jobs[0].config["all_targets"] == ["projects"]


def test_user_config_paths_include_config_toml(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write(home / ".config/chronos/config.toml", _user_target_config("projects"))
    _write(home / ".config/chronos/blender.toml", _user_target_config("blender"))
    monkeypatch.setenv("CHRONOS_ORIGINAL_HOME", str(home))

    jobs = load_user_config_jobs()
    names = sorted(job.path.name for job in jobs if job.path is not None)
    assert names == ["blender.toml", "config.toml"]


def test_list_targets_includes_user_config_toml_job(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write(home / ".config/chronos/config.toml", _user_target_config("projects"))
    monkeypatch.setenv("CHRONOS_ORIGINAL_HOME", str(home))
    jobs = discover_config_jobs_for_run(Plan(mode="backup", selections=["all"], scope="auto"))
    assert len(jobs) == 1
    assert jobs[0].scope == "user"
    assert jobs[0].path is not None and jobs[0].path.name == "config.toml"


def test_system_config_does_not_inherit_home_target(monkeypatch, tmp_path: Path) -> None:
    etc_cfg = tmp_path / "etc/chronos/config.toml"
    _write(etc_cfg, _system_root_config())
    monkeypatch.setattr("chronos.config.SYSTEM_CONFIG_PATH", etc_cfg)
    monkeypatch.setattr("chronos.config.SYSTEM_CONFIG_DROPIN_DIR", tmp_path / "etc/chronos/config.toml.d")

    job = load_merged_system_config()
    assert job is not None
    assert set(job.config["targets"]) == {"root"}


def test_explicit_projects_config_validates_without_builtin_targets(tmp_path: Path) -> None:
    cfg_path = tmp_path / "projects.toml"
    _write(cfg_path, _user_target_config("projects"))

    loaded, _ = load_config(cfg_path)
    assert set(loaded["targets"]) == {"projects"}
    assert loaded["all_targets"] == ["projects"]


def test_list_targets_shows_only_explicit_user_targets(tmp_path: Path) -> None:
    cfg_path = tmp_path / "projects.toml"
    _write(cfg_path, _user_target_config("projects"))
    config, _ = load_config(cfg_path)

    output = io.StringIO()
    with redirect_stdout(output):
        print_list_targets(config)
    text = output.getvalue()
    assert "projects" in text
    assert "root" not in text
    assert "home" not in text
    assert "efi" not in text
    assert "boot" not in text


def test_target_selection_matches_only_correct_scoped_job(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write(home / ".config/chronos/projects.toml", _user_target_config("projects"))
    _write(home / ".config/chronos/blender.toml", _user_target_config("blender"))
    monkeypatch.setenv("CHRONOS_ORIGINAL_HOME", str(home))

    etc_cfg = tmp_path / "etc/chronos/config.toml"
    _write(etc_cfg, _system_root_config())
    monkeypatch.setattr("chronos.config.SYSTEM_CONFIG_PATH", etc_cfg)
    monkeypatch.setattr("chronos.config.SYSTEM_CONFIG_DROPIN_DIR", tmp_path / "etc/chronos/config.toml.d")

    root_jobs = discover_config_jobs_for_run(Plan(mode="backup", selections=["root"], scope="auto"))
    assert len(root_jobs) == 1
    assert root_jobs[0].scope == "system"

    projects_jobs = discover_config_jobs_for_run(
        Plan(mode="backup", selections=["projects"], scope="auto")
    )
    assert len(projects_jobs) == 1
    assert projects_jobs[0].scope == "user"
    assert projects_jobs[0].display_name.endswith("projects.toml")

    blender_jobs = discover_config_jobs_for_run(
        Plan(mode="backup", selections=["blender"], scope="auto")
    )
    assert len(blender_jobs) == 1
    assert blender_jobs[0].scope == "user"
    assert blender_jobs[0].display_name.endswith("blender.toml")


def test_target_selection_finds_projects_in_user_config_toml(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write(home / ".config/chronos/config.toml", _user_target_config("projects"))
    monkeypatch.setenv("CHRONOS_ORIGINAL_HOME", str(home))
    jobs = discover_config_jobs_for_run(Plan(mode="backup", selections=["projects"], scope="auto"))
    assert len(jobs) == 1
    assert jobs[0].scope == "user"
    assert jobs[0].path is not None and jobs[0].path.name == "config.toml"


def test_builtin_fallback_still_works_without_any_configs(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("CHRONOS_ORIGINAL_HOME", str(home))
    monkeypatch.setattr("chronos.config.SYSTEM_CONFIG_PATH", tmp_path / "etc/chronos/config.toml")
    monkeypatch.setattr("chronos.config.SYSTEM_CONFIG_DROPIN_DIR", tmp_path / "etc/chronos/config.toml.d")

    jobs = discover_config_jobs_for_run(Plan(mode="backup", selections=["all"], scope="auto"))
    assert len(jobs) == 1
    assert jobs[0].scope == "builtin"
    assert "root" in jobs[0].config["targets"]


def test_ui_table_is_rejected(tmp_path: Path) -> None:
    cfg_path = tmp_path / "bad.toml"
    _write(
        cfg_path,
        """
backup_dir = "/mnt/storage/bak"
restore_root = "/"
all_targets = ["projects"]

[ui]
extra-info = true

[targets.projects]
src = "/mnt/data0/projects/"
dst = "projects"
""",
    )
    with pytest.raises(RuntimeError, match="unknown top-level key\\(s\\): ui"):
        load_config(cfg_path)
