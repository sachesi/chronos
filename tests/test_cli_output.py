from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from chronos import cli
from chronos.types import ConfigJob, Plan, SELinuxInfo


def _job(*, scope: str = "user") -> ConfigJob:
    return ConfigJob(
        path=None,
        scope=scope,
        display_name=f"{scope}:cfg",
        config={
            "backup_dir": "/mnt/storage/bak",
            "restore_root": "/",
            "all_targets": ["projects"],
            "ui": {"extra-info": False, "progress": "chronos"},
            "targets": {"projects": {"src": "/mnt/data0/projects/", "dst": "projects"}},
            "presets": {},
            "rsync": {"extra_backup_args": [], "extra_restore_args": []},
        },
    )


def test_list_targets_default_is_compact_and_quiet() -> None:
    plan = Plan(list_targets=True, scope="auto")
    buf = io.StringIO()
    with (
        redirect_stdout(buf),
        patch("chronos.cli.parse_args", return_value=plan),
        patch("chronos.cli.discover_config_jobs_for_run", return_value=[_job()]),
        patch("chronos.cli.load_user_ui_defaults", return_value=None),
    ):
        rc = cli.main([])

    out = buf.getvalue()
    assert rc == 0
    assert "targets:" in out
    assert "all targets:" not in out
    assert "SELinux:" not in out
    assert "version:" not in out
    assert "restore root:" not in out
    assert "* = included in -a / all" not in out
    assert out.count("chronos") == 1
    assert "system targets" not in out
    assert "user targets" not in out
    assert "\nuser\n" in out
    assert "* projects" in out


def test_list_targets_extra_info_shows_selinux() -> None:
    plan = Plan(list_targets=True, scope="auto", extra_info=True)
    buf = io.StringIO()
    with (
        redirect_stdout(buf),
        patch("chronos.cli.parse_args", return_value=plan),
        patch("chronos.cli.discover_config_jobs_for_run", return_value=[_job()]),
        patch("chronos.cli.load_user_ui_defaults", return_value=None),
        patch(
            "chronos.cli.selinux_info",
            return_value=SELinuxInfo(present=True, enabled=True, enforcing=True),
        ),
    ):
        rc = cli.main([])

    out = buf.getvalue()
    assert rc == 0
    assert "SELinux:" in out
    assert "version:" in out
    assert "restore root:" in out
    assert "* = included in targets/all for this config" in out


def test_show_config_uses_targets_label_not_all_targets() -> None:
    plan = Plan(show_config=True, scope="auto")
    buf = io.StringIO()
    with (
        redirect_stdout(buf),
        patch("chronos.cli.parse_args", return_value=plan),
        patch("chronos.cli.discover_config_jobs_for_run", return_value=[_job(scope="system")]),
        patch("chronos.cli.load_user_ui_defaults", return_value=None),
    ):
        rc = cli.main([])

    out = buf.getvalue()
    assert rc == 0
    assert "targets:" in out
    assert "all targets:" not in out


def test_list_targets_groups_by_scope() -> None:
    plan = Plan(list_targets=True, scope="auto")
    jobs = [_job(scope="system"), _job(scope="user")]
    jobs[0].path = Path("/etc/chronos/config.toml")
    jobs[0].config["all_targets"] = ["root"]
    jobs[0].config["targets"] = {
        "root": {"src": "/", "dst": "root"},
        "boot": {"src": "/boot/", "dst": "boot"},
    }
    jobs[1].path = Path("/home/alice/.config/chronos/projects.toml")
    jobs[1].config["all_targets"] = ["projects"]
    buf = io.StringIO()
    with (
        redirect_stdout(buf),
        patch("chronos.cli.parse_args", return_value=plan),
        patch("chronos.cli.discover_config_jobs_for_run", return_value=jobs),
        patch("chronos.cli.load_user_ui_defaults", return_value=None),
    ):
        rc = cli.main([])

    out = buf.getvalue()
    assert rc == 0
    assert "system" in out
    assert "user" in out
    assert out.index("\nsystem\n") < out.index("\nuser\n")


def test_backup_output_is_grouped_once_without_repeated_sections() -> None:
    plan = Plan(mode="backup", selections=["all"], scope="auto")
    system_job = _job(scope="system")
    user_job = _job(scope="user")
    system_job.path = Path("/etc/chronos/config.toml")
    user_job.path = Path("/home/alice/.config/chronos/projects.toml")
    system_job.config["targets"] = {"root": {"src": "/", "dst": "root"}}
    system_job.config["all_targets"] = ["root"]
    user_job.config["targets"] = {"projects": {"src": "/mnt/data0/projects", "dst": "projects"}}
    user_job.config["all_targets"] = ["projects"]

    buf = io.StringIO()
    with (
        redirect_stdout(buf),
        patch("chronos.cli.parse_args", return_value=plan),
        patch("chronos.cli.discover_config_jobs_for_run", return_value=[system_job, user_job]),
        patch("chronos.cli.maybe_sudo_escalate", return_value=([system_job, user_job], False)),
        patch("chronos.cli.require_tool"),
        patch("chronos.cli.selinux_info", return_value=SELinuxInfo(True, True, True)),
        patch("chronos.cli.load_user_ui_defaults", return_value=None),
        patch("chronos.cli.selected_job_targets", side_effect=[["root"], ["projects"]]),
        patch("chronos.cli.ensure_backup_mount"),
        patch("chronos.cli.confirm_restore"),
        patch("chronos.cli.backup_scope_lock") as scope_lock_mock,
        patch("chronos.cli.target_lock") as target_lock_mock,
        patch("chronos.cli.backup_target"),
    ):
        scope_lock_mock.return_value.__enter__.return_value = None
        scope_lock_mock.return_value.__exit__.return_value = None
        target_lock_mock.return_value.__enter__.return_value = None
        target_lock_mock.return_value.__exit__.return_value = None
        rc = cli.main(["-ba"])

    out = buf.getvalue()
    assert rc == 0
    assert out.count("chronos backup") == 1
    assert "configs" not in out
    assert out.count("backup completed") == 1
    assert "SELinux:" not in out
    assert "source fs:" not in out
    assert "dest fs:" not in out
    assert "◉ system" in out or ":: system" in out
    assert "◉ user" in out or ":: user" in out


def test_backup_default_hides_incomplete_for_versioned_target() -> None:
    plan = Plan(mode="backup", selections=["all"], scope="auto")
    user_job = _job(scope="user")
    user_job.config["targets"] = {
        "projects": {"src": "/mnt/data0/projects", "dst": "projects", "versioned": True}
    }
    user_job.config["all_targets"] = ["projects"]

    buf = io.StringIO()
    with (
        redirect_stdout(buf),
        patch("chronos.cli.parse_args", return_value=plan),
        patch("chronos.cli.discover_config_jobs_for_run", return_value=[user_job]),
        patch("chronos.cli.maybe_sudo_escalate", return_value=([user_job], False)),
        patch("chronos.cli.require_tool"),
        patch("chronos.cli.selinux_info", return_value=SELinuxInfo(True, True, True)),
        patch("chronos.cli.load_user_ui_defaults", return_value=None),
        patch("chronos.cli.selected_job_targets", return_value=["projects"]),
        patch("chronos.cli.ensure_backup_mount"),
        patch("chronos.cli.confirm_restore"),
        patch("chronos.cli.backup_scope_lock") as scope_lock_mock,
        patch("chronos.cli.target_lock") as target_lock_mock,
        patch("chronos.cli.backup_target"),
    ):
        scope_lock_mock.return_value.__enter__.return_value = None
        scope_lock_mock.return_value.__exit__.return_value = None
        target_lock_mock.return_value.__enter__.return_value = None
        target_lock_mock.return_value.__exit__.return_value = None
        rc = cli.main(["-ba"])

    out = buf.getvalue()
    assert rc == 0
    assert "/projects/current" in out
    assert ".incomplete-" not in out


def test_ascii_mode_uses_ascii_glyphs(monkeypatch) -> None:
    plan = Plan(mode="backup", selections=["all"], scope="auto")
    user_job = _job(scope="user")
    buf = io.StringIO()
    monkeypatch.setenv("CHRONOS_ASCII", "1")
    with (
        redirect_stdout(buf),
        patch("chronos.cli.parse_args", return_value=plan),
        patch("chronos.cli.discover_config_jobs_for_run", return_value=[user_job]),
        patch("chronos.cli.maybe_sudo_escalate", return_value=([user_job], False)),
        patch("chronos.cli.require_tool"),
        patch("chronos.cli.selinux_info", return_value=SELinuxInfo(True, True, True)),
        patch("chronos.cli.load_user_ui_defaults", return_value=None),
        patch("chronos.cli.selected_job_targets", return_value=["projects"]),
        patch("chronos.cli.ensure_backup_mount"),
        patch("chronos.cli.confirm_restore"),
        patch("chronos.cli.backup_scope_lock") as scope_lock_mock,
        patch("chronos.cli.target_lock") as target_lock_mock,
        patch("chronos.cli.backup_target"),
    ):
        scope_lock_mock.return_value.__enter__.return_value = None
        scope_lock_mock.return_value.__exit__.return_value = None
        target_lock_mock.return_value.__enter__.return_value = None
        target_lock_mock.return_value.__exit__.return_value = None
        rc = cli.main(["-ba"])

    out = buf.getvalue()
    assert rc == 0
    assert ":: user" in out
    assert "-> projects" in out
    assert "OK projects" in out
