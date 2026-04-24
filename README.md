# chronos

`chronos` is a configurable Linux backup/restore CLI wrapper around `rsync`.

## Quick start

```bash
chronos -ba
chronos -b projects
chronos -ra
```

## Documentation

- [Documentation index](./doc/README.md)
- [Configuration](./doc/configuration.md)
- [Systemd integration](./doc/systemd.md)
- [CLI reference](./doc/cli.md)
- [Versioned backups](./doc/versioning.md)
- [Restore guide](./doc/restore.md)
- [Security model](./doc/security.md)

For runnable config examples, see [`./doc/examples/`](./doc/examples/system-config.toml).
