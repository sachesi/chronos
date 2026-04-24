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
Chronos uses a lock file at `<backup_dir>/.chronos.lock` with `fcntl` non-blocking exclusive lock to prevent overlapping backup runs to the same backup directory.

## Limitations
- Versioning is convenience retention + dedup strategy, **not** a true offline/air-gapped backup.
- Backups on writable media reachable by the running system are **not** root-compromise proof.
- Protect backups with separate trust boundaries (offline copies, immutable snapshots, or remote hardened storage).
