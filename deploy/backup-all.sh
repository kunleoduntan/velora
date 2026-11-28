#!/bin/sh
# Nightly cron:  15 2 * * *  /srv/velora/backup-all.sh   -- backs up every site, keeps 14 days, then copy OFF the server.
set -e
cd "${VELORA_WORKSPACE:-/srv/velora/myworkspace}"
for site in $(velora list-sites | sed 's/^[ *]*//' | awk '{print $1}' | grep -v '^No$'); do
  velora --site "$site" backup
done
find sites/*/private/backups -name '*.gz' -mtime +14 -delete
# rsync -a sites/*/private/backups/ backup-host:/backups/velora/     # <- off-server copy is what makes it a real backup
