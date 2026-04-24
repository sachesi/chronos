from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from chronos import cli
from chronos.config import DEFAULT_CONFIG, load_config, needs_root
from chronos.types import ConfigJob, Plan


def _job(scope: str, *, requires_root: bool) -> ConfigJob:
    return ConfigJob(
        path=None,
        scope=scope,
        display_name=f"{scope}:cfg",
        config={
            "targets": {
                "all": {"requires_root": requires_root},
            },
            "all_targets": ["all"],
            "backup_dir": "/tmp/bak",
            "restore_root": "/tmp/restore",
        },
    )


def test_maybe_sudo_escalate_runs_only_system_jobs_as_root() -> None:
    jobs = [_job("system", requires_root=True), _job("user", requires_root=False)]
    plan = Plan(mode="backup", selections=["all"], scope="auto")

    with (
        patch("chronos.cli.os.geteuid", return_value=1000),
        patch("chronos.cli.shutil.which", return_value="/usr/bin/sudo"),
        patch("chronos.cli.selected_job_targets", return_value=["all"]),
        patch("chronos.cli.needs_root", side_effect=[True]),
        patch("chronos.cli._original_user_name", return_value="alice"),
        patch("chronos.cli._original_user_home", return_value=Path("/home/alice")),
        patch("chronos.cli.subprocess.run") as run_mock,
        patch("chronos.cli.sys.argv", ["chronos", "-ba"]),
    ):
        run_mock.return_value.returncode = 0
        remaining_jobs = cli.maybe_sudo_escalate(jobs, plan)

    assert [job.scope for job in remaining_jobs] == ["user"]
    assert run_mock.call_count == 1
    cmd = run_mock.call_args.args[0]
    assert "--internal-system-only" in cmd
    assert cmd[:2] == ["/usr/bin/sudo", "chronos"]


def test_main_runs_user_jobs_after_system_sudo_step() -> None:
    jobs = [_job("system", requires_root=True), _job("user", requires_root=False)]

    with (
        patch("chronos.cli.parse_args", return_value=Plan(mode="backup", selections=["all"])),
        patch("chronos.cli.validate_plan"),
        patch("chronos.cli.discover_config_jobs_for_run", return_value=jobs),
        patch("chronos.cli.maybe_sudo_escalate", return_value=[jobs[1]]),
        patch("chronos.cli.require_tool"),
        patch("chronos.cli.selinux_info", return_value=None),
        patch("chronos.cli.print_config_jobs"),
        patch("chronos.cli.print_summary"),
        patch("chronos.cli.ensure_backup_mount"),
        patch("chronos.cli.confirm_restore"),
        patch("chronos.cli.selected_job_targets", return_value=["all"]),
        patch("chronos.cli.backup_lock") as lock_mock,
        patch("chronos.cli.backup_target") as backup_mock,
    ):
        lock_mock.return_value.__enter__.return_value = None
        lock_mock.return_value.__exit__.return_value = None
        rc = cli.main(["-ba"])

    assert rc == 0
    assert backup_mock.call_count == 1


def test_builtin_root_boot_efi_targets_still_require_root() -> None:
    for target in ("root", "efi", "boot"):
        assert DEFAULT_CONFIG["targets"][target]["requires_root"] is True


def test_user_custom_target_outside_home_defaults_to_no_root(tmp_path: Path) -> None:
    cfg = tmp_path / "projects.toml"
    cfg.write_text(
        """
backup_dir = "/mnt/storage/bak"
restore_root = "/tmp/restore"
all_targets = ["projects"]

[targets.projects]
src = "/mnt/storage/data/projects"
dst = "projects"
    """.strip()
    )
    loaded, _ = load_config(cfg)
    assert loaded["targets"]["projects"].get("requires_root", False) is False
    assert needs_root(loaded, ["projects"], "backup") is False
