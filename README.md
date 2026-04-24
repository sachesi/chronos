# chronos

`chronos` is a configurable Linux backup/restore CLI wrapper around `rsync`.

## Quick start

```bash
chronos -ba
chronos -b projects
chronos -ra
```

## Documentation

- [Documentation index](./docs/README.md)
- [Configuration](./docs/configuration.md)
- [Systemd integration](./docs/systemd.md)
- [CLI reference](./docs/cli.md)
- [Versioned backups](./docs/versioning.md)
- [Restore guide](./docs/restore.md)
- [Security model](./docs/security.md)

For runnable config examples, see [`./docs/examples/`](./docs/examples/system-config.toml).
