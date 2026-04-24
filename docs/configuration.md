# Configuration

## Config locations
Chronos uses these paths:

- `/etc/chronos/config.toml`
- `/etc/chronos/config.toml.d/*.toml`
- `~/.config/chronos/config.toml` (UI defaults only)
- `~/.config/chronos/*.toml` (user backup jobs; `config.toml` excluded)

## Merge and separation rules

### System scope
System config is merged in this order:

1. Built-in defaults
2. `/etc/chronos/config.toml` (if present)
3. `/etc/chronos/config.toml.d/*.toml` in lexical order

Later files override earlier values (deep merge for tables).

### User scope
Each user job file (`~/.config/chronos/*.toml`, excluding `config.toml`) is loaded as an independent job by merging:

1. Built-in defaults
2. That one user job file

User job files are **not** merged together.

### `~/.config/chronos/config.toml`
This file is reserved for `[ui]` only. Non-`ui` keys are rejected. Its UI keys are applied only in default manual auto-scope runs (not with `--config`, and not with `--no-interactive`).

## Per-job vs UI-only

### Per-job keys
These affect backup/restore behavior:

- `backup_dir`, `restore_root`, `all_targets`
- `confirm_restore_to_live_root`, `require_backup_mount`
- `check_filesystems`, `auto_disable_unsupported_metadata`
- `touch_autorelabel`, `selinux_xattrs`
- `delete`, `delete_excluded`, `exclude_container_storage`
- `numeric_ids`, `preserve_acls`, `preserve_xattrs`, `preserve_hardlinks`
- `progress` (global on/off)
- `[rsync]` (`extra_backup_args`, `extra_restore_args`)
- `[presets]`
- `[targets.*]`

### UI-only keys
- `[ui].progress` (`chronos`, `rsync`, `none`, `auto`)
- `[ui].extra-info` (`true`/`false`)

Compatibility keys still accepted:
- top-level `progress_style` (legacy alternative to `[ui].progress`)

## Full key reference

### Top-level scalar/list keys

- `backup_dir` (string): root folder where target backups are stored.
- `restore_root` (string): restore destination root; `/` means live system.
- `all_targets` (array[string]): targets expanded by `-a`/`all`.
- `confirm_restore_to_live_root` (bool): prompt before restore.
- `require_backup_mount` (bool): require `backup_dir` to resolve to a mounted filesystem not `/`.
- `check_filesystems` (bool): inspect filesystems before rsync.
- `auto_disable_unsupported_metadata` (bool): auto-disable unsupported ACL/xattr flags instead of failing.
- `touch_autorelabel` (`"auto"|true|false`): create `.autorelabel` on root restore when appropriate.
- `selinux_xattrs` (`"auto"|"preserve"|"exclude"`): SELinux xattr policy.
- `delete` (bool): rsync `--delete`.
- `delete_excluded` (bool): rsync `--delete-excluded` in backup mode.
- `exclude_container_storage` (bool): append default home excludes for rootless container storage.
- `numeric_ids` (bool): rsync `--numeric-ids`.
- `preserve_acls` (bool): include `-A` when supported.
- `preserve_xattrs` (bool): include `-X` when supported.
- `preserve_hardlinks` (bool): include `-H`.
- `progress` (bool): global progress enable/disable.
- `progress_style` (string, deprecated): legacy UI progress style.

### `[ui]`
- `progress` (string): `chronos`, `rsync`, `none`, `auto`.
- `extra-info` (bool): show command and metadata diagnostic detail.

### `[rsync]`
- `extra_backup_args` (array[string])
- `extra_restore_args` (array[string])

### `[presets]`
Each preset is a table (`[presets.<name>]`) with at least one of:

- `targets = [...]` — used for both backup and restore
- `backup_targets = [...]` — used for backup only
- `restore_targets = [...]` — used for restore only

### `[targets.<name>]`
Required:
- `dst` (string)
- exactly one of:
  - `src` (string)
  - `src_candidates` (array[string])

Optional:
- `requires_root` (bool)
- `one_file_system` (bool)
- `mount_required` (bool)
- `backup_exclude` (array[string])
- `restore_exclude` (array[string])
- `create_dirs_after_restore` (array[string], mainly root target)
- `versioned` (bool)
- `keep_versions` (int >= 1, requires `versioned = true`)
- target-level overrides for:
  - `preserve_acls`
  - `preserve_xattrs`
  - `preserve_hardlinks`
