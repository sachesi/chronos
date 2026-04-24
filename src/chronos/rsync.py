from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .config import expand_user_path, original_user_home
from .fs import is_mountpoint
from .output import c, warn, Color
from .types import ChronosError, MetadataDecision, RSyncMessageStats

# Rootless Podman/container storage often contains overlay layers with shifted
# ownership and protected files that a normal user cannot read. Backing it up as
# part of a generic home backup is noisy and usually not what users want.
HOME_CONTAINER_EXCLUDES = [
    ".local/share/containers/storage/***",
    ".local/share/containers/cache/***",
]

PROGRESS_RE = re.compile(
    r"^\s*"
    r"(?P<transferred>[0-9][0-9,\.]*\s*[KMGTPE]?B?)\s+"
    r"(?P<percent>[0-9]{1,3})%\s+"
    r"(?P<rate>\S+)\s+"
    r"(?P<eta>\S+)"
    r"(?:\s+\((?P<details>[^)]*)\))?"
)


# ---------------------------------------------------------------------------
# Progress/UI helpers
# ---------------------------------------------------------------------------

def configured_progress_style(config: dict[str, Any]) -> str:
    """Return the runtime progress style. Config no longer controls UI style."""
    _ = config
    return "auto"


def effective_progress_style(config: dict[str, Any]) -> str:
    """Return the actual progress style for this process.

    Chronos' parser is useful only on an interactive TTY. When output is
    redirected or logged the safe default is no progress output.
    """
    requested = configured_progress_style(config)
    if requested == "auto":
        return "chronos" if sys.stdout.isatty() else "none"
    if requested == "chronos" and not sys.stdout.isatty():
        return "none"
    return requested


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def rsync_log_dir() -> Path:
    return original_user_home() / ".cache" / "chronos" / "logs"


def new_rsync_log_path() -> Path:
    log_dir = rsync_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return log_dir / f"rsync-{stamp}-{os.getpid()}.log"


# ---------------------------------------------------------------------------
# rsync output classification and stats
# ---------------------------------------------------------------------------

def is_rsync_error_line(text: str) -> bool:
    return (
        text.startswith("rsync:")
        or text.startswith("IO error encountered")
        or text.startswith("rsync error:")
    )


def update_rsync_stats(stats: RSyncMessageStats, text: str) -> None:
    stats.total += 1
    lowered = text.lower()
    if "permission denied" in lowered:
        stats.permission_denied += 1
    elif "vanished" in lowered:
        stats.vanished += 1
    elif "skipping file deletion" in lowered:
        stats.deletion_skipped += 1
    else:
        stats.other += 1


def print_rsync_summary(stats: RSyncMessageStats) -> None:
    if stats.total == 0:
        return
    parts = []
    if stats.permission_denied:
        parts.append(f"{stats.permission_denied} permission-denied")
    if stats.vanished:
        parts.append(f"{stats.vanished} vanished")
    if stats.deletion_skipped:
        parts.append(f"{stats.deletion_skipped} deletion-skipped")
    if stats.other:
        parts.append(f"{stats.other} other")
    detail = ", ".join(parts) if parts else f"{stats.total} messages"
    warn(f"rsync reported {detail}; full log: {stats.log_path}")
    if stats.permission_denied:
        warn(
            "permission-denied files were skipped; for home backups this is often "
            "rootless container/overlay storage. Keep the default container-storage "
            "exclude or create a dedicated target for important bind-mounted data."
        )


def classify_rsync_line(line: str) -> tuple[str, re.Match[str] | None]:
    """Classify one rsync output fragment as 'progress', 'progress-no-match', or 'message'."""
    text = line.strip()
    if not text:
        return "empty", None

    match = PROGRESS_RE.match(text)
    if match:
        return "progress", match

    if "to-chk=" in text or "ir-chk=" in text or "xfr#" in text:
        return "progress-no-match", None

    return "message", None


# ---------------------------------------------------------------------------
# rsync execution
# ---------------------------------------------------------------------------

def shlex_join(argv: list[str]) -> str:
    return " ".join(shlex.quote(x) for x in argv)


def run_rsync(
    args: list[str], *, dry_run: bool, progress_style: str = "chronos", show_command: bool = False
) -> None:
    if dry_run:
        args = [*args[:1], "--dry-run", *args[1:]]
    if show_command or dry_run:
        from .output import info
        info(c(shlex_join(args), Color.DIM))

    if progress_style != "chronos" or dry_run:
        proc = subprocess.run(args, check=False)
        if proc.returncode != 0:
            raise ChronosError(f"rsync failed with exit code {proc.returncode}")
        return

    stats = RSyncMessageStats(log_path=new_rsync_log_path())
    log_file = stats.log_path.open("a", encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    log_file.write("$ " + shlex_join(args) + "\n\n")
    log_file.flush()

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None

    last_progress = ""
    pending = ""
    last_render = 0.0

    from .output import terminal_width, render_progress

    def clear_progress_line() -> None:
        nonlocal last_progress
        if last_progress:
            print("\r" + " " * (terminal_width() - 1) + "\r", end="", flush=True)
            last_progress = ""

    def render_match(match: re.Match[str], *, force: bool = False) -> None:
        nonlocal last_progress, last_render
        now = time.monotonic()
        if not force and now - last_render < 0.08:
            return
        groups = match.groupdict()
        percent = max(0, min(100, int(groups["percent"])))
        last_progress = render_progress(
            percent,
            groups["transferred"],
            groups["rate"],
            groups["eta"],
            groups.get("details") or "",
        )
        print("\r" + last_progress, end="", flush=True)
        last_render = now

    def handle_fragment(fragment: str, *, force: bool = False) -> None:
        text = fragment.strip()
        if not text:
            return
        kind, match = classify_rsync_line(text)
        if kind == "progress" and match is not None:
            render_match(match, force=force)
            return
        if kind == "progress-no-match":
            return
        update_rsync_stats(stats, text)
        log_file.write(text + "\n")
        log_file.flush()
        if not is_rsync_error_line(text):
            clear_progress_line()
            print(text)

    try:
        while True:
            ch = proc.stdout.read(1)
            if ch == "" and proc.poll() is not None:
                break
            if ch == "":
                continue
            if ch in "\r\n":
                handle_fragment(pending, force=(ch == "\n"))
                pending = ""
            else:
                pending += ch

        if pending:
            handle_fragment(pending, force=True)

        rc = proc.wait()
        if last_progress:
            print()
        print_rsync_summary(stats)
        if rc != 0:
            message = f"rsync failed with exit code {rc}"
            if stats.log_path:
                message += f"; see {stats.log_path}"
            raise ChronosError(message)
    finally:
        log_file.close()


# ---------------------------------------------------------------------------
# rsync argument building
# ---------------------------------------------------------------------------

def build_rsync_args(
    config: dict[str, Any],
    target_config: dict[str, Any],
    *,
    mode: str,
    metadata: MetadataDecision,
) -> list[str]:
    args = ["rsync"]

    archive = "-a"
    if metadata.preserve_acls:
        archive += "A"
    if metadata.preserve_xattrs:
        archive += "X"
    if target_config.get("preserve_hardlinks", config.get("preserve_hardlinks", True)):
        archive += "H"
    args.append(archive)

    if config.get("numeric_ids", True):
        args.append("--numeric-ids")

    progress_style = effective_progress_style(config)
    if config.get("progress", True) and progress_style in {"rsync", "chronos"}:
        args.append("--info=progress2,name0")

    if config.get("delete", True):
        args.append("--delete")
    if mode == "backup" and config.get("delete_excluded", True):
        args.append("--delete-excluded")
    if target_config.get("one_file_system", False):
        args.append("--one-file-system")

    for rule in metadata.xattr_filter_rules:
        args.append(f"--filter={rule}")

    extra_key = "extra_backup_args" if mode == "backup" else "extra_restore_args"
    args.extend(str(x) for x in config.get("rsync", {}).get(extra_key, []))
    return args


def append_excludes(args: list[str], patterns: list[str]) -> None:
    for pattern in patterns:
        args.append(f"--exclude={pattern}")


def choose_source(target: str, target_config: dict[str, Any]) -> Path:
    if "src_candidates" in target_config:
        for candidate in target_config["src_candidates"]:
            p = expand_user_path(candidate)
            if p.exists() and is_mountpoint(p):
                return p
        candidates = ", ".join(target_config["src_candidates"])
        raise ChronosError(f"no mounted source found for {target}; checked: {candidates}")

    src = expand_user_path(target_config["src"])
    if target_config.get("mount_required", False) and not is_mountpoint(src):
        raise ChronosError(f"{src} is not mounted")
    if not src.exists():
        raise ChronosError(f"source does not exist: {src}")
    return src


def ensure_trailing_slash(path: Path) -> str:
    text = str(path)
    return text if text.endswith("/") else text + "/"


def backup_excludes_for_target(
    config: dict[str, Any], target: str, target_config: dict[str, Any]
) -> list[str]:
    patterns = [str(x) for x in target_config.get("backup_exclude", [])]
    if target == "home" and config.get("exclude_container_storage", True):
        for pattern in HOME_CONTAINER_EXCLUDES:
            if pattern not in patterns:
                patterns.append(pattern)
    return patterns
