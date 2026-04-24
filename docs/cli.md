# CLI reference

## Classic manual workflow
These workflows are supported and unchanged:

```bash
chronos -ba
chronos -b root
chronos -b projects
chronos -ra
```

## Scope and config discovery

- `--scope system|user|auto`
  - `auto` (default): discover both system and user jobs.
  - `system`: only `/etc/chronos/...` merged config.
  - `user`: only `~/.config/chronos/*.toml` jobs.

- `--all-configs`
  - Run all discovered config jobs in scope, even when a target name would otherwise be ambiguous.

- `--list-configs`
  - Print discovered jobs and exit.

## Privilege and prompt controls

- `--no-sudo`
  - Disable sudo re-exec.
  - If selected targets require root, command fails.

- `--no-interactive`
  - Disable interactive prompts.
  - Implies `--yes` for restore confirmation logic.
  - Also prevents sudo prompt escalation.

## Restore-version controls

- `--version NAME`
  - Implemented.
  - Restore a specific version from a versioned target.
  - Valid only in restore mode and with exactly one target.

- `--list-versions TARGET`
  - Implemented.
  - Lists available versions (newest first) and marks current.

## Other important options

- `-c, --config PATH` explicit config file.
- `--backup-dir PATH` temporary runtime override of `backup_dir`.
- `--restore-root PATH` temporary runtime override of `restore_root`.
- `--show-config` print summary.
- `--list-targets` list configured targets and presets.
- `--extra-info` / `--no-extra-info` control verbose diagnostics.

## Not implemented as CLI flags

- `--progress` is **not** an implemented CLI flag. Progress mode is configured via `[ui].progress` and top-level `progress`.
