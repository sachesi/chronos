# Versioned backups

Versioning is per-target.

## Enable

```toml
[targets.projects]
src = "/mnt/data0/projects/"
dst = "projects"
versioned = true
keep_versions = 10
```

- `versioned = true` enables snapshot-style target directories.
- `keep_versions = N` sets retention count (`N >= 1`).

## Layout
For target `projects` under `backup_dir`:

```text
<backup_dir>/projects/
  current -> versions/20260424-213001
  versions/
    20260424-200000/
    20260424-213001/
```

Version directory names use `YYYYmmdd-HHMMSS` (with optional numeric suffix in collision cases).

## How backups are created
- New backup is first written to `.incomplete-<version>`.
- If successful, it is renamed into `versions/<version>`.
- `current` symlink is updated atomically-like (replace existing symlink).
- If a previous `current` exists and resolves safely inside `versions/`, Chronos passes `rsync --link-dest=<previous>` for hard-link dedup behavior.

## Retention behavior
After successful versioned backup, Chronos prunes old version directories:

- keeps newest versions up to `keep_versions`
- never prunes the directory currently pointed to by `current`
- ignores unexpected names/symlinks outside expected safety constraints

## Restore behavior
- Without `--version`, restore uses `current`.
- With `--version NAME`, restore uses `versions/NAME`.
- `--version` is rejected for non-versioned targets.
