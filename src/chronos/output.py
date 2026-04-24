from __future__ import annotations

import os
import shutil
import sys


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"


_INFO_GLYPH = "::"


def use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def ascii_only() -> bool:
    return os.environ.get("CHRONOS_ASCII") == "1"


def glyph(name: str) -> str:
    unicode_glyphs = {
        "info": "::",
        "phase": "◉",
        "start": "→",
        "arrow": "⇢",
        "success": "✓",
        "warning": "!",
        "failure": "✗",
        "progress": "⠋",
    }
    ascii_glyphs = {
        "info": "::",
        "phase": "::",
        "start": "->",
        "arrow": "->",
        "success": "OK",
        "warning": "!",
        "failure": "X",
        "progress": "::",
    }
    table = ascii_glyphs if ascii_only() else unicode_glyphs
    return table.get(name, table["info"])


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return "0s"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, rem = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{rem:02d}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h{mins:02d}m{rem:02d}s"


def c(text: str, color: str) -> str:
    if not use_color():
        return text
    return f"{color}{text}{Color.RESET}"


def info(message: str) -> None:
    print(f"{c(glyph('info'), Color.CYAN)} {message}")


def ok(message: str) -> None:
    print(f"{c(glyph('success'), Color.GREEN)} {message}")


def warn(message: str) -> None:
    print(f"{c(glyph('warning'), Color.YELLOW)} {message}")


def fail(message: str) -> None:
    print(f"{c(glyph('failure'), Color.RED)} {message}", file=sys.stderr)


def section(title: str) -> None:
    width = shutil.get_terminal_size((88, 20)).columns
    label = f" {title} "
    line_len = max(0, width - len(label))
    print()
    print(c(label + "━" * line_len, Color.BOLD + Color.BLUE))


def terminal_width(default: int = 88) -> int:
    return shutil.get_terminal_size((default, 20)).columns


def render_progress(
    percent: int,
    transferred: str,
    rate: str,
    eta: str,
    details: str = "",
) -> str:
    detail = f"  {details}" if details else ""
    prefix = c(glyph("progress"), Color.CYAN)
    return f"{prefix} {percent:3d}%  {transferred.strip():>12}  {rate:<12} eta {eta}{detail}"
