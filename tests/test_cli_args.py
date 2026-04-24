from __future__ import annotations

import pytest

from chronos import __version__
from chronos.cli import parse_args
from chronos.types import ChronosError


def test_dash_dash_version_prints_app_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        parse_args(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_from_version_parses_restore_version() -> None:
    plan = parse_args(["-r", "projects", "--from-version", "20260424-180806"])
    assert plan.mode == "restore"
    assert plan.version == "20260424-180806"


def test_from_version_requires_value() -> None:
    with pytest.raises(ChronosError, match="--from-version needs a version name"):
        parse_args(["--from-version"])
