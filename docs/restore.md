# Restore guide

## Restore safety model
- Chronos can prompt for confirmation before restore (`confirm_restore_to_live_root = true`).
- It prints restore destination and target list.
- If `restore_root` is `/`, it warns that this is the live system root.
- `--no-interactive` disables prompts and requires non-interactive-safe usage.

## `restore_root`
`restore_root` controls where targets are restored:

- `root` target restores to `restore_root` itself.
- Non-root targets restore beneath `restore_root` using their source-like relative paths.
- `efi` restores to mounted `<restore_root>/efi` or `<restore_root>/boot/efi`.

Override once at runtime:

```bash
chronos -ra --restore-root /mnt/sysroot
```

## Restoring to live root
To restore directly to `/`, explicitly confirm (or use `--yes` / `--no-interactive` in automation).

## Restoring from LiveUSB (recommended for full system)
Example sequence:

```bash
sudo mount /dev/mapper/cryptroot /mnt/sysroot
sudo mount /dev/YOUR_ESP /mnt/sysroot/efi
sudo mount /dev/YOUR_BACKUP_DISK /mnt/storage

chronos -ra --restore-root /mnt/sysroot
```

## Versioned restore target
For a versioned target:

```bash
chronos -r projects --version 20260424-213001
```

Without `--version`, restore uses the target `current` symlink.

## Notes for root/efi/boot
- `root`: after restore, Chronos can create `.autorelabel` when SELinux relabel is appropriate.
- `efi`: destination must be a mounted EFI System Partition.
- `boot`: treated as its own target when configured/selected.
