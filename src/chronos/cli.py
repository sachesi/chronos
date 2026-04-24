from __future__ import annotations

import os
import shutil
import sys
import textwrap
from copy import deepcopy
from pathlib import Path

from . import __version__
from .config import (
    APP_NAME,
    apply_ui_overrides,
    backup_dest,
    default_config_path,
    discover_config_jobs_for_run,
    expand_user_path,
    load_user_ui_defaults,
    needs_root,
    normalize_builtin_selection,
    selected_job_targets,
    should_apply_user_ui_defaults,
    write_default_config,
)
from .fs import (
    backup_lock,
    ensure_backup_mount,
    require_tool,
    selinux_info,
)
from .operations import backup_target, confirm_restore, restore_target
from .output import Color, c, fail, info, ok, section, warn
from .types import ChronosError, ConfigJob, Plan
from .versioning import list_target_versions, resolve_current_version, validate_version_name

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def usage() -> str:
    return textwrap.dedent(
        f"""
        {APP_NAME} {__version__}

        Usage:
          chronos -ba                         Backup all configured targets
          chronos -b root -b home -b efi      Backup selected targets
          chronos -ra                         Restore all configured targets
          chronos -r root -r home -r efi      Restore selected targets
          chronos --list-versions projects    List available backup versions for target

        Also works:
          chronos backup all
          chronos restore root home efi
          chronos -b desktop                  Backup a preset or custom target from config

        Options:
          -c, --config PATH           Use another config file
          -n, --dry-run               Show what rsync would do
          -y, --yes                   Do not ask restore confirmation
              --backup-dir PATH       Override backup_dir from config
              --restore-root PATH     Override restore_root from config
          --version NAME          Restore from a specific backup version (restore mode only)
          --list-versions TARGET  List versions for a target (newest first)
          --init-config           Create default ~/.config/chronos/config.toml
              --scope MODE            Config scope: auto|system|user
              --all-configs           Run all discovered configs in selected scope
              --list-configs          Show discovered configs and exit
              --no-sudo               Disable sudo escalation
              --no-interactive        Disable interactive prompts
              --show-config           Print active config path and summary
              --list-targets          Show configured targets and presets
              --extra-info            Show verbose diagnostics, including rsync command
              --no-extra-info         Hide verbose diagnostics even if config enables them
          -h, --help                  Show help

        Default config path:
          {default_config_path()}
        """
    ).strip()


def _add_selection(plan: Plan, selection: str) -> None:
    normalized = normalize_builtin_selection(selection)
    if normalized not in plan.selections:
        plan.selections.append(normalized)


def _set_mode(plan: Plan, mode: str) -> None:
    if plan.mode and plan.mode != mode:
        raise ChronosError("cannot combine backup and restore in one command")
    plan.mode = mode


def _is_option_like(text: str) -> bool:
    return text.startswith("-") and text not in ("/", "/home", "/boot", "/efi", "/boot/efi")


def parse_args(argv: list[str]) -> Plan:
    plan = Plan()
    i = 0

    while i < len(argv):
        arg = argv[i]

        if arg in ("-h", "--help"):
            print(usage())
            raise SystemExit(0)
        elif arg == "version":
            print(__version__)
            raise SystemExit(0)
        elif arg in ("-c", "--config"):
            i += 1
            if i >= len(argv):
                raise ChronosError(f"{arg} needs a path")
            plan.config_path = expand_user_path(argv[i])
        elif arg.startswith("--config="):
            plan.config_path = expand_user_path(arg.split("=", 1)[1])
        elif arg == "--backup-dir":
            i += 1
            if i >= len(argv):
                raise ChronosError("--backup-dir needs a path")
            plan.backup_dir_override = argv[i]
        elif arg.startswith("--backup-dir="):
            plan.backup_dir_override = arg.split("=", 1)[1]
        elif arg == "--restore-root":
            i += 1
            if i >= len(argv):
                raise ChronosError("--restore-root needs a path")
            plan.restore_root_override = argv[i]
        elif arg.startswith("--restore-root="):
            plan.restore_root_override = arg.split("=", 1)[1]
        elif arg in ("-n", "--dry-run"):
            plan.dry_run = True
        elif arg in ("-y", "--yes"):
            plan.yes = True
        elif arg == "--init-config":
            plan.init_config = True
        elif arg == "--all-configs":
            plan.all_configs = True
        elif arg == "--list-configs":
            plan.list_configs = True
        elif arg == "--no-sudo":
            plan.no_sudo = True
        elif arg == "--no-interactive":
            plan.no_interactive = True
        elif arg == "--scope":
            i += 1
            if i >= len(argv):
                raise ChronosError("--scope needs one of: auto, system, user")
            plan.scope = argv[i]
        elif arg.startswith("--scope="):
            plan.scope = arg.split("=", 1)[1]
        elif arg == "--show-config":
            plan.show_config = True
        elif arg == "--list-targets":
            plan.list_targets = True
        elif arg == "--version":
            i += 1
            if i >= len(argv):
                raise ChronosError("--version needs a version name")
            plan.version = argv[i]
        elif arg.startswith("--version="):
            plan.version = arg.split("=", 1)[1]
        elif arg == "--list-versions":
            i += 1
            if i >= len(argv):
                raise ChronosError("--list-versions needs a target")
            if plan.list_versions_target is not None:
                raise ChronosError("--list-versions can be used only once")
            plan.list_versions_target = normalize_builtin_selection(argv[i])
        elif arg.startswith("--list-versions="):
            if plan.list_versions_target is not None:
                raise ChronosError("--list-versions can be used only once")
            plan.list_versions_target = normalize_builtin_selection(arg.split("=", 1)[1])
        elif arg == "--extra-info":
            plan.extra_info = True
        elif arg == "--no-extra-info":
            plan.extra_info = False
        elif arg in ("backup", "bak"):
            _set_mode(plan, "backup")
        elif arg in ("restore", "rst"):
            _set_mode(plan, "restore")
        elif arg in ("-b", "--backup"):
            _set_mode(plan, "backup")
            if i + 1 < len(argv) and not _is_option_like(argv[i + 1]):
                i += 1
                _add_selection(plan, argv[i])
        elif arg in ("-r", "--restore"):
            _set_mode(plan, "restore")
            if i + 1 < len(argv) and not _is_option_like(argv[i + 1]):
                i += 1
                _add_selection(plan, argv[i])
        elif arg.startswith("-") and not arg.startswith("--"):
            for ch in arg[1:]:
                if ch == "b":
                    _set_mode(plan, "backup")
                elif ch == "r":
                    _set_mode(plan, "restore")
                elif ch == "a":
                    _add_selection(plan, "all")
                elif ch == "n":
                    plan.dry_run = True
                elif ch == "y":
                    plan.yes = True
                elif ch == "h":
                    print(usage())
                    raise SystemExit(0)
                else:
                    raise ChronosError(f"unknown short option: -{ch}")
        elif not _is_option_like(arg):
            _add_selection(plan, arg)
        else:
            raise ChronosError(f"unknown argument: {arg}")

        i += 1

    return plan


def validate_plan(plan: Plan) -> None:
    if plan.scope not in {"auto", "system", "user"}:
        raise ChronosError("--scope must be one of: auto, system, user")
    if plan.version is not None:
        validate_version_name(plan.version)
        if plan.mode != "restore":
            raise ChronosError("--version requires restore mode")
        if len(plan.selections) != 1:
            raise ChronosError("--version can be used with exactly one restore target")
    if plan.list_versions_target is not None and plan.mode:
        raise ChronosError("--list-versions cannot be combined with backup or restore mode")
    if plan.no_interactive:
        plan.yes = True


# ---------------------------------------------------------------------------
# Privilege escalation
# ---------------------------------------------------------------------------


def maybe_sudo_escalate(jobs: list[ConfigJob], plan: Plan) -> None:
    """Re-exec through sudo only when the selected operation needs root."""
    if os.geteuid() == 0:
        return

    needs_any_root = False
    for job in jobs:
        if job.scope == "user":
            continue
        targets = selected_job_targets(job, plan)
        if needs_root(job.config, targets, plan.mode):
            needs_any_root = True
            break

    if not needs_any_root:
        return

    if plan.no_sudo:
        raise ChronosError("selected target requires root, but sudo escalation is disabled")

    sudo = shutil.which("sudo")
    if sudo is None:
        raise ChronosError(
            "root privileges are required for selected targets, but sudo was not found"
        )
    if plan.no_interactive:
        raise ChronosError(
            "selected target requires root, but --no-interactive forbids sudo prompt"
        )

    env_args = [
        f"CHRONOS_ORIGINAL_USER={_original_user_name()}",
        f"CHRONOS_ORIGINAL_HOME={_original_user_home()}",
    ]
    info("root privileges required for selected targets — re-running with sudo…")
    os.execvp(sudo, [sudo, *env_args, sys.argv[0], *sys.argv[1:]])


def _original_user_name() -> str:
    from .config import original_user_name

    return original_user_name()


def _original_user_home() -> Path:
    from .config import original_user_home

    return original_user_home()


# ---------------------------------------------------------------------------
# Display / listing helpers
# ---------------------------------------------------------------------------


def print_summary(
    config: dict,
    config_path: Path | None,
    targets: list[str] | None = None,
    selinux=None,
) -> None:
    section(APP_NAME)
    print(f"{c('version:', Color.BOLD)}      {__version__}")
    print(
        f"{c('config:', Color.BOLD)}       {config_path if config_path else '(built-in defaults)'}"
    )
    print(f"{c('backup dir:', Color.BOLD)}   {config['backup_dir']}")
    print(f"{c('restore root:', Color.BOLD)} {config['restore_root']}")
    print(f"{c('all targets:', Color.BOLD)}  {', '.join(config.get('all_targets', []))}")
    if selinux is not None:
        print(f"{c('SELinux:', Color.BOLD)}      {selinux.summary()}")
    if targets is not None:
        print(f"{c('selected:', Color.BOLD)}     {', '.join(targets)}")


def print_list_targets(config: dict) -> None:
    section("targets")
    for name, target in config.get("targets", {}).items():
        src = target.get("src") or ", ".join(target.get("src_candidates", []))
        in_all = name in config.get("all_targets", [])
        marker = c("*", Color.GREEN) if in_all else " "
        print(f" {marker} {c(name, Color.BOLD):<20} {src:<30} -> {backup_dest(config, name)}")
    print()
    print("* = included in -a / all")

    presets = config.get("presets", {})
    if presets:
        section("presets")
        for name, preset in presets.items():
            if isinstance(preset, list):
                desc = ", ".join(str(x) for x in preset)
            elif isinstance(preset, dict):
                parts = []
                if "targets" in preset:
                    parts.append("targets=" + ",".join(str(x) for x in preset["targets"]))
                if "backup_targets" in preset:
                    parts.append("backup=" + ",".join(str(x) for x in preset["backup_targets"]))
                if "restore_targets" in preset:
                    parts.append("restore=" + ",".join(str(x) for x in preset["restore_targets"]))
                desc = "  ".join(parts)
            else:
                desc = "invalid"
            print(f"   {c(name, Color.BOLD):<20} {desc}")


def print_list_versions(config: dict, target: str) -> None:
    configured = config.get("targets", {})
    if target not in configured:
        raise ChronosError(f"target not configured: {target}")
    target_config = configured[target]
    if not target_config.get("versioned", False):
        print(f"target is not versioned: {target}")
        return

    versions = list_target_versions(config, target)
    current_name = None
    current_resolved = resolve_current_version(config, target)
    if current_resolved is not None:
        current_name = current_resolved.name

    print(f"{target}:")
    for name in versions:
        marker = "  current" if name == current_name else ""
        print(f"  {name}{marker}")


def print_config_jobs(jobs: list[ConfigJob]) -> None:
    section("configs")
    if not jobs:
        print("  (none)")
        return
    for job in jobs:
        print(f"  {job.scope:<8} {job.display_name}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    try:
        plan = parse_args(argv)
        validate_plan(plan)

        if plan.init_config:
            write_default_config(plan.config_path)
            return 0

        jobs = discover_config_jobs_for_run(plan)
        user_ui_defaults = load_user_ui_defaults() if should_apply_user_ui_defaults(plan) else None

        if plan.list_configs:
            print_config_jobs(jobs)
            return 0

        if plan.dry_run:
            warn("dry-run enabled")

        if plan.show_config:
            sel = selinux_info()
            for job in jobs:
                print_summary(job.config, job.path, selinux=sel)
            return 0

        if plan.list_targets and not plan.mode:
            sel = selinux_info()
            for job in jobs:
                print_summary(job.config, job.path, selinux=sel)
                print_list_targets(job.config)
            return 0

        if plan.list_versions_target is not None and not plan.mode:
            for job in jobs:
                if plan.list_versions_target in job.config.get("targets", {}):
                    print_list_versions(job.config, plan.list_versions_target)
                    return 0
            raise ChronosError(f"target not configured: {plan.list_versions_target}")

        if not plan.mode:
            print(usage())
            return 2

        maybe_sudo_escalate(jobs, plan)

        require_tool("rsync")
        require_tool("findmnt")
        require_tool("mountpoint")

        sel = selinux_info()
        print_config_jobs(jobs)

        for job in jobs:
            config = deepcopy(job.config)
            if plan.backup_dir_override:
                config["backup_dir"] = plan.backup_dir_override
            if plan.restore_root_override:
                config["restore_root"] = plan.restore_root_override
            config = apply_ui_overrides(config, plan, user_ui_defaults)

            targets = selected_job_targets(job, plan)
            if plan.version is not None and len(targets) != 1:
                raise ChronosError("--version can be used with exactly one restore target")
            if os.geteuid() != 0 and needs_root(config, targets, plan.mode):
                if plan.no_sudo:
                    raise ChronosError(
                        f"target {targets[0]} requires root, but sudo escalation is disabled"
                    )

            print_summary(config, job.path, targets, selinux=sel)
            if plan.list_targets:
                print_list_targets(config)
                continue
            if plan.list_versions_target is not None:
                print_list_versions(config, plan.list_versions_target)
                continue

            backup_dir = expand_user_path(config["backup_dir"])
            ensure_backup_mount(backup_dir, config.get("require_backup_mount", True))
            with backup_lock(backup_dir):
                confirm_restore(config, plan, targets)
                for target in targets:
                    if plan.mode == "backup":
                        backup_target(config, target, dry_run=plan.dry_run, selinux=sel)
                    else:
                        restore_target(
                            config,
                            target,
                            dry_run=plan.dry_run,
                            selinux=sel,
                            requested_version=plan.version,
                        )

        section("done")
        ok("all selected operations completed")
        return 0

    except KeyboardInterrupt:
        fail("interrupted")
        return 130
    except ChronosError as e:
        fail(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
