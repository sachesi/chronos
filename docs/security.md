# Security model and limitations

## sudo behavior
Chronos may re-exec itself through `sudo` when selected jobs/targets need root and caller is non-root.

- Root is required for targets with `requires_root = true` (built-in: `root`, `efi`, `boot`). This applies to both backup and restore.
- User-scope jobs skip sudo escalation entirely. Targets with `requires_root = false` (the default) run without root for both backup and restore.

## `--no-sudo`
With `--no-sudo`, Chronos will not escalate.

- If selected target requires root, operation fails cleanly.

## Custom targets outside home
Paths outside `$HOME` (for example `/mnt/data0/projects`) do **not** automatically imply sudo. Root is used only if target config sets `requires_root = true` or restore mode requires root privileges.

## System targets require root
Built-in system targets (`root`, `boot`, `efi`) are root-required for backup; restore path handling is root-sensitive and generally expected to run as root.

## SELinux and xattrs
Chronos evaluates filesystem support and SELinux behavior:

- can auto-disable unsupported ACL/xattr preservation when configured
- supports SELinux xattr policy modes (`auto`, `preserve`, `exclude`)
- in auto/exclude flows, excludes `security.*` xattrs while preserving others where possible
- can create `.autorelabel` after root restore

## Backup directory locking
Chronos uses three `fcntl` non-blocking lock levels:

- **System lock**: `<backup_dir>/.chronos-system.lock`
  - Used by system jobs and any selected target with `requires_root = true`.
  - Prevents overlapping system orchestrators on the same `backup_dir`.
- **User global lock**: `<backup_dir>/.chronos-user.lock`
  - Used by user jobs when selected targets do not require root.
  - Prevents overlapping user orchestrators on the same `backup_dir`.
- **Target lock**: `<backup_dir>/<dst>/.chronos-target.lock`
  - Used for each target operation (backup/restore/version/current/prune path).
  - Prevents concurrent operations touching the same target destination.

Lock acquisition order is always global scope lock first, then target lock.

Permissions guidance:

- user backups need write access to `<backup_dir>` to create/open `.chronos-user.lock`
- user backups need write access to `<backup_dir>/<dst>` to create/open `.chronos-target.lock`
- `.chronos-system.lock` may be root-owned and should not block user jobs by itself

Legacy `<backup_dir>/.chronos.lock` is ignored.

## Limitations
- Versioning is convenience retention + dedup strategy, **not** a true offline/air-gapped backup.
- Backups on writable media reachable by the running system are **not** root-compromise proof.
- Protect backups with separate trust boundaries (offline copies, immutable snapshots, or remote hardened storage).
