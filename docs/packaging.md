# Packaging notes (RPM)

## RPM asset layout
The spec installs packaged assets into:

- System units: `/usr/lib/systemd/system`
- User units: `/usr/lib/systemd/user`
- Main config: `/etc/chronos/config.toml`
- Drop-in dir: `/etc/chronos/config.toml.d/`
- Example config: `/usr/share/chronos/config.toml.example`
- Shell completions:
  - bash: `/usr/share/bash-completion/completions/chronos`
  - fish: `/usr/share/fish/vendor_completions.d/chronos.fish`
  - zsh: `/usr/share/zsh/site-functions/_chronos`

## Config file semantics
`/etc/chronos/config.toml` is packaged as `%config(noreplace)`, so local changes are preserved across upgrades.

## systemd behavior in package
Units/timers are installed by default, but timer enablement is left to admins/users.

## COPR/SRPM context
`chronos.spec` is set up for RPM workflows and references GitHub tag archives (`Source0`) suitable for SRPM/COPR-style builds.
