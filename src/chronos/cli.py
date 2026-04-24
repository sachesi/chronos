from __future__ import annotations

import os
import shutil
import subprocess
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
    extra_info_enabled,
    expand_user_path,
    load_user_ui_defaults,
    needs_root,
    normalize_builtin_selection,
    selected_job_targets,
    should_apply_user_ui_defaults,
    write_default_config,
)
from .fs import (
    backup_scope_lock,
    ensure_backup_mount,
    require_tool,
    selinux_info,
    target_lock,
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
        elif arg == "--internal-system-only":
            plan.internal_system_only = True
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


def maybe_sudo_escalate(jobs: list[ConfigJob], plan: Plan) -> tuple[list[ConfigJob], bool]:
    """Run system jobs with sudo when needed while keeping user jobs in user context."""
    if plan.internal_system_only:
        return [job for job in jobs if job.scope != "user"], False

    split_by_scope = plan.config_path is None and plan.scope == "auto"
    if split_by_scope:
        system_jobs = [job for job in jobs if job.scope != "user"]
        user_jobs = [job for job in jobs if job.scope == "user"]
    else:
        system_jobs = jobs
        user_jobs = []

    if os.geteuid() == 0:
        return system_jobs if plan.internal_system_only else jobs, False

    needs_any_root = False
    for job in system_jobs:
        targets = selected_job_targets(job, plan)
        if needs_root(job.config, targets, plan.mode):
            needs_any_root = True
            break

    if not needs_any_root:
        return jobs, False

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

    cmd = [sudo, sys.argv[0], *sys.argv[1:], "--internal-system-only"]
    env = dict(os.environ)
    env["CHRONOS_ORIGINAL_USER"] = _original_user_name()
    env["CHRONOS_ORIGINAL_HOME"] = str(_original_user_home())

    info("root privileges required for selected system targets — running them with sudo…")
    result = subprocess.run(cmd, env=env, check=False)  # noqa: S603
    if result.returncode != 0:
        raise ChronosError(f"system job run with sudo failed (exit status {result.returncode})")

    return user_jobs, True


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
    *,
    compact: bool = False,
    show_extra: bool = False,
) -> None:
    section(APP_NAME)
    if not compact or show_extra:
        print(f"{c('version:', Color.BOLD)}      {__version__}")
    print(
        f"{c('config:', Color.BOLD)}       {config_path if config_path else '(built-in defaults)'}"
    )
    backup_label = "backup:" if compact else "backup dir:"
    print(f"{c(backup_label, Color.BOLD)}   {config['backup_dir']}")
    if not compact or show_extra:
        print(f"{c('restore root:', Color.BOLD)} {config['restore_root']}")
    print(f"{c('targets:', Color.BOLD)}      {', '.join(config.get('all_targets', []))}")
    if show_extra and selinux is not None:
        print(f"{c('SELinux:', Color.BOLD)}      {selinux.summary()}")
    if targets is not None:
        print(f"{c('selected:', Color.BOLD)}     {', '.join(targets)}")


def print_list_targets(config: dict, *, scope: str | None = None) -> None:
    section(f"{scope} targets" if scope else "targets")
    for name, target in config.get("targets", {}).items():
        src = target.get("src") or ", ".join(target.get("src_candidates", []))
        print(f"  {c(name, Color.BOLD):<20} {src:<30} -> {backup_dest(config, name)}")

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


def print_targets_overview(
    jobs: list[ConfigJob], plan: Plan, user_ui_defaults: dict[str, object] | None
) -> None:
    prepared: list[tuple[ConfigJob, dict, bool]] = []
    for job in jobs:
        config = apply_ui_overrides(deepcopy(job.config), plan, user_ui_defaults)
        prepared.append((job, config, extra_info_enabled(config)))

    sel = selinux_info() if any(show_extra for _, _, show_extra in prepared) else None
    section(APP_NAME)

    grouped: dict[str, list[tuple[ConfigJob, dict, bool]]] = {}
    for entry in prepared:
        grouped.setdefault(entry[0].scope, []).append(entry)

    preferred_order = ["system", "user", "explicit", "builtin"]
    ordered_scopes = [scope for scope in preferred_order if scope in grouped]
    ordered_scopes.extend(sorted(scope for scope in grouped if scope not in preferred_order))

    for scope in ordered_scopes:
        print()
        print(c(scope, Color.BOLD))
        for job, config, show_extra in grouped[scope]:
            print(f"  {c('config:', Color.BOLD)}  {job.path if job.path else '(built-in defaults)'}")
            print(f"  {c('backup:', Color.BOLD)}  {config['backup_dir']}")
            print(f"  {c('targets:', Color.BOLD)} {', '.join(config.get('all_targets', []))}")
            if show_extra:
                print(f"  {c('version:', Color.BOLD)} {__version__}")
                print(f"  {c('restore root:', Color.BOLD)} {config['restore_root']}")
                if sel is not None:
                    print(f"  {c('SELinux:', Color.BOLD)} {sel.summary()}")
            print()
            for name, target in config.get("targets", {}).items():
                src = target.get("src") or ", ".join(target.get("src_candidates", []))
                marker = "*" if name in config.get("all_targets", []) else " "
                print(f"    {marker} {c(name, Color.BOLD):<10} {src:<26} -> {backup_dest(config, name)}")
            if show_extra:
                print("    * = included in targets/all for this config")
            print()


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


def print_run_header(plan: Plan) -> None:
    title = f"{APP_NAME} {plan.mode}"
    if plan.dry_run:
        title += " dry-run"
    section(title)
    if plan.dry_run:
        info("dry-run: no files will be changed")


def print_job_header(
    job: ConfigJob,
    config: dict[str, object],
    targets: list[str],
    *,
    mode: str,
    show_extra: bool,
    selinux,
) -> None:
    print()
    print(c(job.scope, Color.BOLD))
    print(f"  {c('config:', Color.BOLD)}  {job.path if job.path else '(built-in defaults)'}")
    print(f"  {c('backup:', Color.BOLD)}  {config['backup_dir']}")
    print(f"  {c('targets:', Color.BOLD)} {', '.join(targets)}")
    if mode == "restore":
        print(f"  {c('restore root:', Color.BOLD)} {config['restore_root']}")
    if show_extra:
        print(f"  {c('version:', Color.BOLD)} {__version__}")
        if selinux is not None:
            print(f"  {c('SELinux:', Color.BOLD)} {selinux.summary()}")
    print()


def display_target_source(config: dict, target: str) -> str:
    target_config = config["targets"][target]
    return target_config.get("src") or ", ".join(target_config.get("src_candidates", []))


def display_target_destination(config: dict, target: str, mode: str) -> Path:
    destination = backup_dest(config, target)
    target_config = config["targets"][target]
    if mode == "backup" and bool(target_config.get("versioned", False)):
        return destination / "current"
    return destination


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
            for job in jobs:
                config = apply_ui_overrides(deepcopy(job.config), plan, user_ui_defaults)
                show_extra = extra_info_enabled(config)
                sel = selinux_info() if show_extra else None
                print_summary(config, job.path, selinux=sel, show_extra=show_extra)
            return 0

        if plan.list_targets and not plan.mode:
            print_targets_overview(jobs, plan, user_ui_defaults)
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

        jobs, system_phase_ran = maybe_sudo_escalate(jobs, plan)

        require_tool("rsync")
        require_tool("findmnt")
        require_tool("mountpoint")

        sel = selinux_info()
        if not system_phase_ran or not jobs:
            print_run_header(plan)
        scope_counts: dict[str, int] = {}

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

            show_extra = extra_info_enabled(config)
            print_job_header(
                job,
                config,
                targets,
                mode=plan.mode,
                show_extra=show_extra,
                selinux=sel if show_extra else None,
            )
            if plan.list_targets:
                print_list_targets(config)
                continue
            if plan.list_versions_target is not None:
                print_list_versions(config, plan.list_versions_target)
                continue

            backup_dir = expand_user_path(config["backup_dir"])
            ensure_backup_mount(backup_dir, config.get("require_backup_mount", True))
            with backup_scope_lock(config, job, targets):
                confirm_restore(config, plan, targets)
                for target in targets:
                    source = display_target_source(config, target)
                    destination = display_target_destination(config, target, plan.mode)
                    print(f"  {c(target, Color.BOLD):<10} {source:<26} -> {destination}")
                    with target_lock(config, target):
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
                        scope_counts[job.scope] = scope_counts.get(job.scope, 0) + 1

        section("done")
        for scope, completed in sorted(scope_counts.items()):
            print(f"  {scope:<8} {completed} completed")
        return 0

    except KeyboardInterrupt:
        fail("interrupted")
        return 130
    except ChronosError as e:
        fail(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
