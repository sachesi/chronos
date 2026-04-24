# Chronos Documentation

## Overview
Chronos is a Linux backup/restore CLI built around `rsync`. It is configuration-driven and can run either manually (`chronos ...`) or from systemd timers. It supports:

- system targets (`root`, `boot`, `efi`)
- user targets (`home` and custom user-readable paths)
- multi-config job discovery (`/etc/chronos` + `~/.config/chronos`)
- optional per-target versioned backups (`versions/YYYYmmdd-HHMMSS` + `current` symlink)

## Scope model: system vs user
Chronos separates jobs by configuration scope:

- **System scope**: `/etc/chronos/config.toml` plus `/etc/chronos/config.toml.d/*.toml` merged in lexical order.
- **User scope**: every `~/.config/chronos/*.toml` file **except** `config.toml`; each file is a separate backup job.
- **User UI defaults file**: `~/.config/chronos/config.toml` is reserved for `[ui]` defaults only.

Operationally:

- `--scope system` runs only system config jobs.
- `--scope user` runs only user config jobs.
- `--scope auto` (default) discovers both.

## Quick start
```bash
chronos -ba
chronos -b projects
chronos -ra
```

Enable timers (examples):

```bash
sudo systemctl enable --now chronos-backup.timer
systemctl --user enable --now chronos-user-backup.timer
```

## Table of contents
- [Configuration](./configuration.md)
- [Systemd services and timers](./systemd.md)
- [CLI reference](./cli.md)
- [Versioned backups](./versioning.md)
- [Restore guide](./restore.md)
- [Packaging](./packaging.md)
- [Security model and limitations](./security.md)
- [Examples](./examples/system-config.toml), [projects job](./examples/projects.toml), [games job](./examples/games.toml)
