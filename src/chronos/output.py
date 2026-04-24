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


def c(text: str, color: str) -> str:
    if not use_color():
        return text
    return f"{color}{text}{Color.RESET}"


def info(message: str) -> None:
    print(f"{c(_INFO_GLYPH, Color.CYAN)} {message}")


def ok(message: str) -> None:
    print(f"{c('✓', Color.GREEN)} {message}")


def warn(message: str) -> None:
    print(f"{c('!', Color.YELLOW)} {message}")


def fail(message: str) -> None:
    print(f"{c('✗', Color.RED)} {message}", file=sys.stderr)


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
    prefix = c(_INFO_GLYPH, Color.CYAN)
    return f"{prefix} {percent:3d}%  {transferred.strip():>12}  {rate:<12} eta {eta}{detail}"
