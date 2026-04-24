from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from chronos.fs import (
    backup_scope_lock,
    lock_path_for_scope,
    lock_path_for_target,
    scope_lock_kind,
    target_lock,
)
from chronos.types import ChronosError, ConfigJob


def _config(tmp_path: Path, target_name: str = "projects", *, requires_root: bool = False) -> dict:
    return {
        "backup_dir": str(tmp_path / "bak"),
        "targets": {target_name: {"dst": target_name, "requires_root": requires_root}},
        "all_targets": [target_name],
    }


def test_lock_path_selection(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert lock_path_for_scope(config, "system") == tmp_path / "bak" / ".chronos-system.lock"
    assert lock_path_for_scope(config, "user") == tmp_path / "bak" / ".chronos-user.lock"
    assert lock_path_for_target(config, "projects") == tmp_path / "bak" / "projects" / ".chronos-target.lock"


def test_scope_kind_selection() -> None:
    job_system = ConfigJob(path=None, scope="system", config={}, display_name="system")
    job_user = ConfigJob(path=None, scope="user", config={}, display_name="user")
    config = {"targets": {"projects": {"requires_root": False}, "root": {"requires_root": True}}}
    assert scope_lock_kind(job_system, config, ["projects"]) == "system"
    assert scope_lock_kind(job_user, config, ["root"]) == "system"
    assert scope_lock_kind(job_user, config, ["projects"]) == "user"


def test_user_job_does_not_open_system_lock(tmp_path: Path) -> None:
    config = _config(tmp_path, "projects", requires_root=False)
    job = ConfigJob(path=None, scope="user", config=config, display_name="user")
    opened: list[str] = []
    real_open = os.open

    def tracking_open(path: str, flags: int, mode: int = 0o777) -> int:
        opened.append(path)
        return real_open(path, flags, mode)

    with patch("chronos.fs.os.open", side_effect=tracking_open):
        with backup_scope_lock(config, job, ["projects"]):
            pass
    assert any(str(path).endswith(".chronos-user.lock") for path in opened)
    assert not any(str(path).endswith(".chronos-system.lock") for path in opened)


def test_system_job_does_not_open_user_lock(tmp_path: Path) -> None:
    config = _config(tmp_path, "root", requires_root=True)
    job = ConfigJob(path=None, scope="system", config=config, display_name="system")
    opened: list[str] = []
    real_open = os.open

    def tracking_open(path: str, flags: int, mode: int = 0o777) -> int:
        opened.append(path)
        return real_open(path, flags, mode)

    with patch("chronos.fs.os.open", side_effect=tracking_open):
        with backup_scope_lock(config, job, ["root"]):
            pass
    assert any(str(path).endswith(".chronos-system.lock") for path in opened)
    assert not any(str(path).endswith(".chronos-user.lock") for path in opened)


def test_scope_lock_permission_error_becomes_chronos_error(tmp_path: Path) -> None:
    config = _config(tmp_path, "projects", requires_root=False)
    job = ConfigJob(path=None, scope="user", config=config, display_name="user")
    with patch("chronos.fs.os.open", side_effect=PermissionError("denied")):
        with pytest.raises(ChronosError, match=r"cannot create/open user backup lock .*permission denied"):
            with backup_scope_lock(config, job, ["projects"]):
                pass


def test_target_lock_permission_error_becomes_chronos_error(tmp_path: Path) -> None:
    config = _config(tmp_path, "projects", requires_root=False)
    with patch("chronos.fs.os.open", side_effect=PermissionError("denied")):
        with pytest.raises(ChronosError, match=r"cannot create/open target lock .*permission denied"):
            with target_lock(config, "projects"):
                pass


def test_scope_lock_conflict_errors(tmp_path: Path) -> None:
    config = _config(tmp_path, "projects", requires_root=False)
    user_job = ConfigJob(path=None, scope="user", config=config, display_name="user")
    system_job = ConfigJob(path=None, scope="system", config=config, display_name="system")

    with backup_scope_lock(config, user_job, ["projects"]):
        with pytest.raises(ChronosError, match="another chronos user backup is already running"):
            with backup_scope_lock(config, user_job, ["projects"]):
                pass

    with backup_scope_lock(config, system_job, ["projects"]):
        with pytest.raises(ChronosError, match="another chronos system backup is already running"):
            with backup_scope_lock(config, system_job, ["projects"]):
                pass


def test_system_and_user_scope_different_locks_do_not_conflict(tmp_path: Path) -> None:
    config = _config(tmp_path, "projects", requires_root=False)
    user_job = ConfigJob(path=None, scope="user", config=config, display_name="user")
    system_job = ConfigJob(path=None, scope="system", config=config, display_name="system")
    with backup_scope_lock(config, user_job, ["projects"]):
        with backup_scope_lock(config, system_job, ["projects"]):
            pass


def test_target_lock_conflict_on_same_target(tmp_path: Path) -> None:
    config = _config(tmp_path, "projects", requires_root=False)
    with target_lock(config, "projects"):
        with pytest.raises(ChronosError, match="another chronos operation is already touching target projects"):
            with target_lock(config, "projects"):
                pass
