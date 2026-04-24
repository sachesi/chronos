# chronos

`chronos` is a small Python CLI wrapper around `rsync` for configurable Linux system backup and restore workflows.

It is packaged for Fedora/COPR for now, but the application itself is not distro-specific. The default config targets a common Linux desktop/server layout:

- `/` and the current user's home backed up separately by default
- EFI System Partition target available explicitly from `/efi` or `/boot/efi`
- backup directory at `/mnt/storage/bak`
- Linux metadata preservation when the source and destination filesystems support it

The default rsync behavior for Linux filesystems is equivalent to:

```bash
-aAXH --numeric-ids
```

`chronos` inspects source and destination filesystems before each backup/restore. If it detects a filesystem that clearly cannot preserve ACLs or xattrs, such as a FAT/exFAT-style EFI partition, it disables the unsupported rsync flags for that target and prints a warning. If SELinux is detected, it reports the SELinux status and handles `security.selinux` separately from normal xattrs: in `auto` mode it preserves real labels only when the destination allows them, otherwise it excludes only `security.selinux` and keeps other xattrs.

## Install from source

```bash
python3 -m pip install --user .
```

Or build/install the RPM from `chronos.spec`.

## Basic usage

Backup all configured targets:

```bash
chronos -ba
```

Backup selected targets:

```bash
chronos -b root -b home -b efi
```

Dry-run:

```bash
chronos -ban
```

Restore all configured targets:

```bash
chronos -ra
```

Restore selected targets:

```bash
chronos -r root -r home -r efi
```

Restore into a mounted system from LiveUSB:

```bash
sudo mount /dev/mapper/cryptroot /mnt/sysroot
sudo mount /dev/YOUR_ESP /mnt/sysroot/efi
sudo mount /dev/YOUR_BACKUP_DISK /mnt/storage

chronos -ra --restore-root /mnt/sysroot
```

Use a different config:

```bash
chronos -ba -c ./my-config.toml
```

## Config

Default config path:

```text
~/.config/chronos/config.toml
```

Create it:

```bash
chronos --init-config
```

Show detected config, SELinux status, targets, and presets:

```bash
chronos --show-config
chronos --list-targets
```

Default backup layout:

```text
/mnt/storage/bak/root
/mnt/storage/bak/home/$USER
# optional explicit target:
/mnt/storage/bak/efi
```

`boot` and `efi` exist as optional targets, but are not included in `all_targets` by default. On systems where `/boot` is just a normal directory under `/`, it is already included in `root`. If `/boot` is a separate mount and you need it, add it to `all_targets`:

```toml
all_targets = ["root", "home", "efi", "boot"]
```

## Custom targets and presets

Yes: custom backup/restore presets are supported through config.

A custom target:

```toml
[targets.projects]
src = "/mnt/data0/projects/"
dst = "projects"
one_file_system = true
backup_exclude = ["*/target/***", "*/.git/***/objects/***"]
restore_exclude = []
```

A normal preset:

```toml
[presets.desktop]
targets = ["root", "home", "efi", "projects"]
```

Use it like this. Chronos will ask for sudo only when the selected targets require it:

```bash
chronos -b desktop
chronos -r desktop
```

A mode-specific preset:

```toml
[presets.fast]
backup_targets = ["home", "projects"]
restore_targets = ["home"]
```

Then:

```bash
sudo chronos backup fast
sudo chronos restore fast
```
