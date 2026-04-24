# systemd integration

Chronos ships timer/service units for both system and user scopes.

## Installed units

### System units
- `chronos.service`
- `chronos.timer`

Service command:

```bash
/usr/bin/chronos backup --scope system --all-configs --no-interactive --no-extra-info
```

This backs up **system-scope configs only** (`/etc/chronos/...`).

### User units
- `chronos.service`
- `chronos.timer`

Service command:

```bash
/usr/bin/chronos backup --scope user --all-configs --no-sudo --no-interactive --no-extra-info
```

This backs up **user-scope configs only** (`~/.config/chronos/*.toml`, including `config.toml`).

## Enable timers
Timers are installed by the package but are **not enabled automatically**.

Enable system timer:

```bash
sudo systemctl enable --now chronos.timer
```

Enable user timer:

```bash
systemctl --user enable --now chronos.timer
```

## User timers when logged out (lingering)
If you want user timers to run without an active login session:

```bash
loginctl enable-linger "$USER"
```

## Timer defaults
Both timers are configured as daily with persistence and a randomized delay:

- `OnCalendar=daily`
- `Persistent=true`
- `RandomizedDelaySec=30min`
- `AccuracySec=5min`
