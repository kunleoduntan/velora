#!/usr/bin/env bash
# Velora uninstaller: ONE command. Always takes a final backup first. Safe to re-run.
#
#   sudo bash uninstall.sh [--purge] [--yes] [--root /srv/velora] [--dry-run]
#
# Default: stops and removes the service, timer, web-server site and `velora` command, and KEEPS your data (workspace, databases, backups) so a later
# install picks up exactly where you left off. With --purge it also DROPS every company database and the PostgreSQL role, deletes the workspace and the
# 'velora' user - after saving a final backup archive outside the workspace (in /root).
set -euo pipefail

ROOT="/srv/velora" PURGE=0 YES=0 DRY=0
usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1; shift;;
    --yes) YES=1; shift;;
    --root) ROOT="${2:?}"; shift 2;;
    --dry-run) DRY=1; shift;;
    -h|--help) usage 0;;
    *) echo "Unknown option: $1" >&2; usage 2;;
  esac
done
run() { if [ "$DRY" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }
say() { printf '\n==> %s\n' "$*"; }
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "Error: run as root (sudo bash uninstall.sh ...)." >&2; exit 1; }

WS="$ROOT/workspace"; VEL="$ROOT/venv/bin/velora"
say "This will remove Velora from this server"
echo "  - stop and remove the 'velora' service, the update timer, the nginx site and the /usr/local/bin/velora command"
if [ "$PURGE" = 1 ]; then
  echo "  - DELETE every company database, the PostgreSQL role, $ROOT and the 'velora' user"
  echo "  - first: save a final backup archive in /root (including the encryption key)"
else
  echo "  - KEEP $ROOT (workspace, databases, backups): installing again later picks up where you left off"
fi
if [ "$YES" = 0 ] && [ "$DRY" = 0 ]; then
  [ -t 0 ] || { echo "Error: not a terminal; re-run with --yes to confirm." >&2; exit 1; }
  read -r -p "Continue? [y/N] " ans
  case "$ans" in y|Y|yes|YES) ;; *) echo "Cancelled."; exit 0;; esac
fi

if [ "$PURGE" = 1 ] && [ "$DRY" = 0 ] && [ -d "$WS" ]; then
  # A purge deletes the files that hold the database credentials, so it must be certain it can drop the databases FIRST.
  [ -x "$VEL" ] && [ -f "$ROOT/.db-root-password" ] || {
    echo "Error: cannot purge safely: $VEL or $ROOT/.db-root-password is missing, so the databases could not be dropped (and deleting the files would orphan them)." >&2
    echo "Nothing was changed. Restore them, or run without --purge, or drop the databases yourself first." >&2
    exit 1
  }
fi

STAMP="$(date +%Y%m%d-%H%M%S)"; ARCHIVE="/root/velora-final-backup-$STAMP.tar.gz"
say "1/4 Final backup"
if [ "$DRY" = 1 ]; then
  echo "+ runuser -u velora -- $VEL backup --all   (every company + the control plane)"
  echo "+ tar czf $ARCHIVE  $WS/backups  $WS/platform/master.key  (mode 600)"
elif [ -x "$VEL" ] && [ -d "$WS" ]; then
  runuser -u velora -- env VELORA_WORKSPACE="$WS" "$VEL" backup --all || echo "Warning: the backup command reported a problem; the archive below still holds the files that exist."
  umask 077
  tar czf "$ARCHIVE" -C "$WS" backups platform/master.key 2>/dev/null || tar czf "$ARCHIVE" -C "$WS" backups
  chmod 600 "$ARCHIVE"
  echo "Saved $ARCHIVE  (keep it safe: it contains the key that decrypts your company database passwords)"
else
  echo "Nothing to back up (no installation found at $ROOT)."
fi

say "2/4 Services"
for u in velora-update.timer velora-update.service velora.service; do
  run systemctl disable --now "$u" 2>/dev/null || true
done
run rm -f /etc/systemd/system/velora.service /etc/systemd/system/velora-update.service /etc/systemd/system/velora-update.timer /etc/sudoers.d/velora /usr/local/bin/velora /usr/local/sbin/velora-domain
run systemctl daemon-reload || true                  # (containers and WSL have no systemd: that must not stop the uninstall)
if [ "$DRY" = 1 ]; then
  echo "+ rm -f /etc/nginx/sites-*/velora /etc/nginx/sites-*/velora-*   (the main site and every company address) && systemctl reload nginx"
elif [ -e /etc/nginx/sites-enabled/velora ] || compgen -G "/etc/nginx/sites-enabled/velora-*" >/dev/null; then
  rm -f /etc/nginx/sites-enabled/velora /etc/nginx/sites-available/velora /etc/nginx/sites-enabled/velora-* /etc/nginx/sites-available/velora-*      # the main site and every company address
  if command -v nginx >/dev/null && nginx -t >/dev/null 2>&1; then systemctl reload nginx; fi
fi

if [ "$PURGE" = 1 ]; then
  say "3/4 Databases"
  FAILED=0
  if [ "$DRY" = 1 ]; then
    echo "+ velora company drop <each company> --yes   (drops its PostgreSQL database and role)"
    echo "+ DROP DATABASE + ROLE of the control plane (velora_cp_*, read from $WS/platform/control_plane.json)"
    echo "+ DROP ROLE velora_root"
  elif [ -x "$VEL" ] && [ -f "$ROOT/.db-root-password" ]; then
    PW="$(cat "$ROOT/.db-root-password")"
    for c in $(runuser -u velora -- env VELORA_WORKSPACE="$WS" "$VEL" company list 2>/dev/null | awk '$1 ~ /^COMP-/ {print $1}'); do
      runuser -u velora -- env VELORA_WORKSPACE="$WS" "$VEL" company drop "$c" --yes --db-root-user velora_root --db-root-password "$PW" || { echo "Error: could not drop $c" >&2; FAILED=1; }
    done
    # the control plane (identity + company registry) has its own database and role when Velora created them
    CP="$WS/platform/control_plane.json"
    if [ -f "$CP" ]; then
      CPNAME="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['db_name'] if d.get('db_type') == 'postgres' and d.get('provisioned_db') else '')" "$CP" 2>/dev/null || true)"
      CPUSER="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('db_user') or '')" "$CP" 2>/dev/null || true)"
      if [[ "$CPNAME" =~ ^velora_cp_[0-9a-f]+$ ]]; then                       # only ever drop a name that matches what Velora generates
        runuser -u postgres -- psql -qc "DROP DATABASE IF EXISTS \"$CPNAME\" WITH (FORCE)" || { echo "Error: could not drop $CPNAME" >&2; FAILED=1; }
        if [[ "$CPUSER" =~ ^velora_cp_[0-9a-f]+$ ]]; then runuser -u postgres -- psql -qc "DROP ROLE IF EXISTS \"$CPUSER\"" || true; fi
      fi
    fi
    runuser -u postgres -- psql -qc "DROP ROLE IF EXISTS velora_root" 2>/dev/null || true
  fi
  if [ "$FAILED" = 1 ]; then
    echo "Some databases could not be dropped. The files and the 'velora' user were KEPT so you can fix the problem and run this again. Your final backup: $ARCHIVE" >&2
    exit 1
  fi
  say "4/4 Files and user"
  run rm -rf "$ROOT"
  run userdel velora 2>/dev/null || true
else
  say "3/4 Databases"; echo "Kept."
  say "4/4 Files"; echo "Kept: $ROOT"
fi

say "Done"
if [ "$PURGE" = 1 ]; then echo "Final backup: $ARCHIVE"; else echo "Your data is still in $ROOT and PostgreSQL. Reinstall any time with install.sh."; fi
echo "Not removed: PostgreSQL, nginx and Python themselves (other things may use them)."
