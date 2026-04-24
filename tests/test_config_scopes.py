from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronos.cli import (  # noqa: E402
    DEFAULT_CONFIG,
    ChronosError,
    Plan,
    apply_ui_overrides,
    confirm_restore,
    discover_config_jobs_for_run,
    load_merged_system_config,
    load_user_ui_defaults,
    load_user_config_jobs,
    maybe_sudo_escalate,
    parse_args,
    selected_job_targets,
    system_config_paths,
    user_config_paths,
    validate_plan,
)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def scoped_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, Path]:
    system_main = tmp_path / "etc" / "chronos" / "config.toml"
    system_drop = tmp_path / "etc" / "chronos" / "config.toml.d"
    home = tmp_path / "home" / "alice"
    monkeypatch.setattr("chronos.cli.SYSTEM_CONFIG_PATH", system_main)
    monkeypatch.setattr("chronos.cli.SYSTEM_CONFIG_DROPIN_DIR", system_drop)
    monkeypatch.setenv("CHRONOS_ORIGINAL_HOME", str(home))
    monkeypatch.setenv("CHRONOS_ORIGINAL_USER", "alice")
    return system_main, system_drop, home


def test_auto_all_discovers_system_and_user_configs(scoped_paths: tuple[Path, Path, Path]) -> None:
    system_main, _, home = scoped_paths
    write(system_main, 'all_targets=["root"]\n')
    write(home / ".config/chronos/projects.toml", 'all_targets=["projects"]\n[targets.projects]\nsrc="/tmp"\ndst="projects"\n')

    plan = parse_args(["-ba"])
    validate_plan(plan)
    jobs = discover_config_jobs_for_run(plan)

    assert [j.scope for j in jobs] == ["system", "user"]


def test_explicit_config_only_uses_explicit(tmp_path: Path) -> None:
    cfg = write(tmp_path / "explicit.toml", 'all_targets=["home"]\n')
    plan = parse_args(["-ba", "-c", str(cfg)])
    validate_plan(plan)
    jobs = discover_config_jobs_for_run(plan)
    assert len(jobs) == 1
    assert jobs[0].scope == "explicit"


def test_explicit_user_config_toml_still_allowed(tmp_path: Path) -> None:
    cfg = write(
        tmp_path / "config.toml",
        'all_targets=["projects"]\n[targets.projects]\nsrc="/tmp"\ndst="projects"\n',
    )
    plan = parse_args(["-ba", "-c", str(cfg)])
    validate_plan(plan)
    jobs = discover_config_jobs_for_run(plan)
    assert len(jobs) == 1
    assert jobs[0].scope == "explicit"


def test_scope_system_only(scoped_paths: tuple[Path, Path, Path]) -> None:
    system_main, _, home = scoped_paths
    write(system_main, 'all_targets=["root"]\n')
    write(home / ".config/chronos/u.toml", 'all_targets=["home"]\n')
    plan = parse_args(["-ba", "--scope", "system"])
    validate_plan(plan)
    jobs = discover_config_jobs_for_run(plan)
    assert [j.scope for j in jobs] == ["system"]


def test_scope_user_only(scoped_paths: tuple[Path, Path, Path]) -> None:
    system_main, _, home = scoped_paths
    write(system_main, 'all_targets=["root"]\n')
    write(home / ".config/chronos/u.toml", 'all_targets=["home"]\n')
    plan = parse_args(["-ba", "--scope=user"])
    validate_plan(plan)
    jobs = discover_config_jobs_for_run(plan)
    assert [j.scope for j in jobs] == ["user"]


def test_system_dropins_merge_in_lexical_order(scoped_paths: tuple[Path, Path, Path]) -> None:
    system_main, system_drop, _ = scoped_paths
    write(system_main, 'all_targets=["root"]\n')
    write(system_drop / "20.toml", 'all_targets=["boot"]\n')
    write(system_drop / "10.toml", 'all_targets=["efi"]\n')
    job = load_merged_system_config()
    assert job is not None
    assert job.config["all_targets"] == ["boot"]


def test_user_configs_are_separate_jobs(scoped_paths: tuple[Path, Path, Path]) -> None:
    _, _, home = scoped_paths
    write(home / ".config/chronos/a.toml", 'all_targets=["home"]\n')
    write(home / ".config/chronos/b.toml", 'all_targets=["home"]\n')
    jobs = load_user_config_jobs()
    assert len(jobs) == 2
    assert jobs[0].path != jobs[1].path


def test_no_sudo_with_root_target_fails_cleanly(scoped_paths: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    system_main, _, _ = scoped_paths
    write(system_main, 'all_targets=["root"]\n')
    plan = parse_args(["-ba", "--scope", "system", "--no-sudo"])
    validate_plan(plan)
    jobs = discover_config_jobs_for_run(plan)
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    with pytest.raises(ChronosError, match="requires root, but sudo escalation is disabled"):
        maybe_sudo_escalate(jobs, plan)


def test_no_interactive_restore_does_not_prompt() -> None:
    plan = Plan(mode="restore", selections=["root"], no_interactive=True, yes=True)
    confirm_restore({"confirm_restore_to_live_root": True, "restore_root": "/"}, plan, ["root"])


def test_ambiguous_target_name_across_configs_fails(scoped_paths: tuple[Path, Path, Path]) -> None:
    system_main, _, home = scoped_paths
    write(system_main, 'all_targets=["projects"]\n[targets.projects]\nsrc="/srv/projects"\ndst="projects"\nrequires_root=true\n')
    write(home / ".config/chronos/projects.toml", 'all_targets=["projects"]\n[targets.projects]\nsrc="~/projects"\ndst="projects"\n')

    plan = parse_args(["-b", "projects"])
    validate_plan(plan)
    with pytest.raises(ChronosError, match="ambiguous"):
        discover_config_jobs_for_run(plan)


def test_systemd_assets_exist() -> None:
    assert Path("assets/usr/lib/systemd/system/chronos-backup.service").exists()
    assert Path("assets/usr/lib/systemd/system/chronos-backup.timer").exists()
    assert Path("assets/usr/lib/systemd/user/chronos-user-backup.service").exists()
    assert Path("assets/usr/lib/systemd/user/chronos-user-backup.timer").exists()


def test_spec_installs_systemd_and_etc_config() -> None:
    text = Path("chronos.spec").read_text(encoding="utf-8")
    assert "chronos-backup.service" in text
    assert "chronos-user-backup.service" in text
    assert "%{_sysconfdir}/chronos/config.toml" in text
    assert "%config(noreplace)" in text


def test_user_config_paths_filters_temp_files(scoped_paths: tuple[Path, Path, Path]) -> None:
    _, _, home = scoped_paths
    write(home / ".config/chronos/a.toml", "all_targets=['home']\n")
    write(home / ".config/chronos/config.toml", "[ui]\nprogress='none'\n")
    write(home / ".config/chronos/a.toml.bak", "")
    write(home / ".config/chronos/.hidden.toml", "")
    paths = user_config_paths()
    assert len(paths) == 1
    assert paths[0].name == "a.toml"


def test_system_config_paths_include_main_and_dropins(scoped_paths: tuple[Path, Path, Path]) -> None:
    system_main, system_drop, _ = scoped_paths
    write(system_main, "all_targets=['root']\n")
    write(system_drop / "20.toml", "all_targets=['root']\n")
    write(system_drop / "10.toml", "all_targets=['root']\n")
    paths = system_config_paths()
    assert paths[0] == system_main
    assert [p.name for p in paths[1:]] == ["10.toml", "20.toml"]


def test_user_ui_defaults_config_with_non_ui_keys_fails(scoped_paths: tuple[Path, Path, Path]) -> None:
    _, _, home = scoped_paths
    write(home / ".config/chronos/config.toml", "backup_dir='/tmp/bak'\n[ui]\nprogress='none'\n")
    with pytest.raises(ChronosError, match="reserved for user UI defaults"):
        load_user_ui_defaults()


def test_user_ui_defaults_override_job_ui_in_manual_auto_mode() -> None:
    config = {
        **DEFAULT_CONFIG,
        "ui": {"progress": "chronos", "extra-info": False},
    }
    plan = Plan(mode="backup", selections=["all"], scope="auto")
    result = apply_ui_overrides(config, plan, {"progress": "none"})
    assert result["ui"]["progress"] == "none"


def test_no_interactive_does_not_apply_cross_scope_ui_defaults() -> None:
    config = {
        **DEFAULT_CONFIG,
        "ui": {"progress": "chronos", "extra-info": False},
    }
    plan = Plan(mode="backup", selections=["all"], scope="auto", no_interactive=True)
    result = apply_ui_overrides(config, plan, {"progress": "none"})
    assert result["ui"]["progress"] == "chronos"
