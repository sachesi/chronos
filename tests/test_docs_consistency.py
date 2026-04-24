from __future__ import annotations

from pathlib import Path

from chronos import __version__


def test_docs_examples_do_not_use_ui_table() -> None:
    for path in Path("docs/examples").glob("*.toml"):
        text = path.read_text(encoding="utf-8")
        assert "[ui]" not in text
        assert "progress_style" not in text

    packaged = [
        Path("assets/etc/chronos/config.toml"),
        Path("assets/usr/share/chronos/config.toml.example"),
    ]
    for path in packaged:
        text = path.read_text(encoding="utf-8")
        assert "[ui]" not in text
        assert "progress_style" not in text


def test_version_is_consistent_with_project_files() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    spec = Path("chronos.spec").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject
    assert f"Version:        {__version__}" in spec
