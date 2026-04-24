Name:           chronos
Version:        0.2.1
Release:        1%{?dist}
Summary:        Configurable rsync backup and restore helper for Linux

License:        GPL-3.0-or-later
URL:            https://github.com/sachesi/chronos
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/%{name}-%{version}.tar.gz
%{!?_unitdir:%global _unitdir %{_prefix}/lib/systemd/system}
%{!?_userunitdir:%global _userunitdir %{_prefix}/lib/systemd/user}

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros

Requires:       python3
Requires:       rsync

%description
Chronos is a configurable rsync-based backup and restore helper for Linux.
It supports built-in and custom backup targets, presets, shell completions,
and metadata-aware rsync behavior.

%prep
%autosetup

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install

# Fix Python package permissions after pip install.
find %{buildroot}%{python3_sitelib}/%{name} -type d -exec chmod 0755 '{}' +
find %{buildroot}%{python3_sitelib}/%{name} -type f -exec chmod 0644 '{}' +

find %{buildroot}%{python3_sitelib}/%{name}-%{version}.dist-info -type d -exec chmod 0755 '{}' +
find %{buildroot}%{python3_sitelib}/%{name}-%{version}.dist-info -type f -exec chmod 0644 '{}' +

# Fix generated console script permission.
chmod 0755 %{buildroot}%{_bindir}/%{name}

%pyproject_save_files -l %{name}

install -Dm0644 assets/usr/share/chronos/config.toml.example \
    %{buildroot}%{_datadir}/%{name}/config.toml.example

install -Dm0644 assets/usr/share/bash-completion/completions/%{name} \
    %{buildroot}%{_datadir}/bash-completion/completions/%{name}

install -Dm0644 assets/usr/share/fish/completions/%{name}.fish \
    %{buildroot}%{_datadir}/fish/vendor_completions.d/%{name}.fish

install -Dm0644 assets/usr/share/zsh/site-functions/_%{name} \
    %{buildroot}%{_datadir}/zsh/site-functions/_%{name}

install -Dm0644 assets/usr/lib/systemd/system/chronos.service \
    %{buildroot}%{_unitdir}/chronos.service
install -Dm0644 assets/usr/lib/systemd/system/chronos.timer \
    %{buildroot}%{_unitdir}/chronos.timer
install -Dm0644 assets/usr/lib/systemd/user/chronos.service \
    %{buildroot}%{_userunitdir}/chronos.service
install -Dm0644 assets/usr/lib/systemd/user/chronos.timer \
    %{buildroot}%{_userunitdir}/chronos.timer

install -Dm0644 assets/etc/chronos/config.toml \
    %{buildroot}%{_sysconfdir}/chronos/config.toml
mkdir -p %{buildroot}%{_sysconfdir}/chronos/config.toml.d

find %{buildroot}%{_datadir}/%{name} -type d -exec chmod 0755 '{}' +
find %{buildroot}%{_datadir}/%{name} -type f -exec chmod 0644 '{}' +

chmod 0644 %{buildroot}%{_datadir}/bash-completion/completions/%{name}
chmod 0644 %{buildroot}%{_datadir}/fish/vendor_completions.d/%{name}.fish
chmod 0644 %{buildroot}%{_datadir}/zsh/site-functions/_%{name}

%check
%pyproject_check_import chronos chronos.cli

%files -f %{pyproject_files}
%doc README.md

%attr(0755,root,root) %{_bindir}/%{name}

%dir %attr(0755,root,root) %{_datadir}/%{name}
%attr(0644,root,root) %{_datadir}/%{name}/config.toml.example

%attr(0644,root,root) %{_datadir}/bash-completion/completions/%{name}
%attr(0644,root,root) %{_datadir}/fish/vendor_completions.d/%{name}.fish
%attr(0644,root,root) %{_datadir}/zsh/site-functions/_%{name}

%attr(0644,root,root) %{_unitdir}/chronos.service
%attr(0644,root,root) %{_unitdir}/chronos.timer
%attr(0644,root,root) %{_userunitdir}/chronos.service
%attr(0644,root,root) %{_userunitdir}/chronos.timer

%dir %attr(0755,root,root) %{_sysconfdir}/chronos
%dir %attr(0755,root,root) %{_sysconfdir}/chronos/config.toml.d
%config(noreplace) %attr(0644,root,root) %{_sysconfdir}/chronos/config.toml

%changelog
* Fri Apr 24 2026 sachesi <sachesi@example.com> - 0.2.1-1
- Make --version report Chronos version directly
- Rename restore snapshot selector to --from-version
- Update completions and docs for version flags

* Fri Apr 24 2026 sachesi <sachesi@example.com> - 0.2.0-1
- Align docs with scoped system/user config workflow
- Keep efi and boot available but not enabled by default
- Remove config-driven UI settings; use --extra-info for diagnostics
- Refine grouped terminal output and locking behavior

* Fri Apr 24 2026 sachesi <sachesi.com> - 0.1.0-12
- Fix fish completion path to use vendor_completions.d

* Fri Apr 24 2026 sachesi <sachesi.com> - 0.1.0-11
- Replace visual progress bar with compact rsync progress2 text line
- Hide full rsync command by default; add --extra-info and --no-extra-info

* Fri Apr 24 2026 sachesi <sachesi@example.com> - 0.1.0-10
- Keep Chronos progress bar clean by logging rsync warnings and printing a summary
- Exclude rootless container storage from home backups by default
- Add rsync warning logs under ~/.cache/chronos/logs


* Fri Apr 24 2026 sachesi <sachesi@example.com> - 0.1.0-8
- Protect SELinux security.* xattrs on sender and receiver sides to avoid rsync lremovexattr spam

* Fri Apr 24 2026 sachesi <sachesi@example.com> - 0.1.0-7
- Restore smart sudo escalation from Claude history
- Default all target is root and current-user home only
- Store home backups under backup_dir/home/<username>
- Preserve invoking user's home/config path across sudo re-exec
- Add Chronos progress bar wrapper for rsync progress2 output

* Fri Apr 24 2026 sachesi <sachesi@example.com> - 0.1.0-5
- Ensure Python package files are included in RPM payload
- Check chronos.cli import during build
- Normalize installed file permissions

* Fri Apr 24 2026 chronos packager <packager@chronos> - 0.1.0-4
- Handle SELinux security.selinux xattr separately from normal xattrs
- Auto-exclude security.selinux when destination policy denies relabel operations

* Fri Apr 24 2026 chronos packager <packager@chronos> - 0.1.0-3
- Make application description distro-neutral
- Add filesystem/SELinux detection and custom preset support

* Fri Apr 24 2026 chronos packager <packager@chronos> - 0.1.0-2
- Match project packaging layout with assets/usr/share completions
- Use GitHub tag archive Source0 for COPR builds

* Fri Apr 24 2026 chronos packager <packager@chronos> - 0.1.0-1
- Initial package
