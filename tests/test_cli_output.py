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
    assert "\nsystem\n" in out
    assert "\nuser\n" in out
    assert out.index("\nsystem\n") < out.index("\nuser\n")
