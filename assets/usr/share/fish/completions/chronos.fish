# fish completion for chronos
complete -c chronos -f
complete -c chronos -s h -l help -d 'Show help'
complete -c chronos -l version -d 'Show version'
complete -c chronos -s b -l backup -d 'Backup mode'
complete -c chronos -s r -l restore -d 'Restore mode'
complete -c chronos -s a -l all -d 'Select all configured targets'
complete -c chronos -s c -l config -d 'Use config file' -r -F
complete -c chronos -s n -l dry-run -d 'Dry-run rsync'
complete -c chronos -s y -l yes -d 'Skip restore confirmation'
complete -c chronos -l backup-dir -d 'Override backup directory' -r -F
complete -c chronos -l restore-root -d 'Override restore root' -r -F
complete -c chronos -l from-version -d 'Restore from backup version' -r
complete -c chronos -l list-versions -d 'List backup versions for target' -r
complete -c chronos -l init-config -d 'Create default config'
complete -c chronos -l show-config -d 'Show config summary'
complete -c chronos -l list-targets -d 'List configured targets'
complete -c chronos -a 'backup bak restore rst' -d 'Mode'
complete -c chronos -a 'all root home efi esp boot / /home /efi /boot /boot/efi' -d 'Target'
complete -c chronos -l extra-info -d 'Show verbose diagnostics, including rsync command'
complete -c chronos -l no-extra-info -d 'Hide verbose diagnostics'
