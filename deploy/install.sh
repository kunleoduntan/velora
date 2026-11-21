#!/usr/bin/env bash
# Velora server installer for Ubuntu/Debian: PostgreSQL + Velora + systemd (+ nginx + TLS). Safe to re-run.
#
#   sudo bash install.sh --email you@company.com --company "My Company" [--domain erp.example.com] [--extras pdf,data,ml] [--auto-update daily|weekly] [--source PIP_SPEC] [--allow-eol] [--python-version 3.12] [--pg-version 16] [--dry-run]
#
# ONE command does everything: packages, a 'velora' user, a virtualenv and a workspace in /srv/velora, PostgreSQL, your first company (with notifications and search built in),
# ONE systemd service (the web server and its background worker run together), a `velora` command that works from anywhere (`sudo velora update`),
# and, with --domain, nginx + Let's Encrypt. Re-running it upgrades an existing installation. Remove it all with uninstall.sh.
set -euo pipefail

EMAIL="" COMPANY="My Company" DOMAIN="" SOURCE="velora" ROOT="/srv/velora" DRY=0 NO_TLS=0 PORT=8000 EXTRAS="" AUTO="" ALLOW_EOL=0 PY_VERSION="3.12" PG_VERSION="16"
usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --email) EMAIL="${2:?}"; shift 2;;
    --company) COMPANY="${2:?}"; shift 2;;
    --domain) DOMAIN="${2:?}"; shift 2;;
    --source) SOURCE="${2:?}"; shift 2;;
    --root) ROOT="${2:?}"; shift 2;;
    --port) PORT="${2:?}"; shift 2;;
    --extras) EXTRAS="${2:?}"; shift 2;;
    --auto-update) AUTO="${2:?}"; shift 2;;
    --allow-eol) ALLOW_EOL=1; shift;;
    --python-version) PY_VERSION="${2:?}"; shift 2;;
    --pg-version) PG_VERSION="${2:?}"; shift 2;;
    --no-tls) NO_TLS=1; shift;;
    --dry-run) DRY=1; shift;;
    -h|--help) usage 0;;
    *) echo "Unknown option: $1" >&2; usage 2;;
  esac
done
[ -n "$EMAIL" ] || { echo "Error: --email is required (the first administrator)." >&2; usage 2; }
case "$AUTO" in ""|daily|weekly) ;; *) echo "Error: --auto-update must be daily or weekly." >&2; exit 2;; esac
case "$EMAIL" in *@*.*) ;; *) echo "Error: '$EMAIL' is not an email address." >&2; exit 2;; esac
[[ "$PY_VERSION" =~ ^3\.(1[0-9])$ ]] || { echo "Error: --python-version must be 3.10 to 3.19 (default 3.12)." >&2; exit 2; }
[[ "$PG_VERSION" =~ ^(1[3-9]|2[0-9])$ ]] || { echo "Error: --pg-version must be 13 or newer (default 16)." >&2; exit 2; }

run() { if [ "$DRY" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }
say() { printf '\n==> %s\n' "$*"; }
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "Error: run as root (sudo bash install.sh ...)." >&2; exit 1; }
[ "$DRY" = 1 ] || command -v apt-get >/dev/null || { echo "Error: this installer supports Ubuntu/Debian (apt)." >&2; exit 1; }

# ---- BEGIN install_uv (identical in install.sh and install-dev.sh: a test keeps them in step)
# Download the uv tool (a fast Python installer) for this CPU into DEST, verifying its published checksum. It lets us use a private, up-to-date Python on ANY Linux/macOS,
# however old the system Python is (Ubuntu 18.04 has 3.6, 20.04 has 3.8), without touching the system Python and without a PPA.
install_uv() {
  dest="$1"
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)  triple="x86_64-unknown-linux-gnu";;
    Linux-aarch64) triple="aarch64-unknown-linux-gnu";;
    Darwin-arm64)  triple="aarch64-apple-darwin";;
    Darwin-x86_64) triple="x86_64-apple-darwin";;
    *) echo "Error: no private Python is available for $(uname -s) $(uname -m). Install Python 3.10+ yourself and run: pip install velora" >&2; return 1;;
  esac
  base="https://github.com/astral-sh/uv/releases/latest/download/uv-$triple"
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/uv.tar.gz" "$base.tar.gz" && curl -fsSL -o "$tmp/uv.sha256" "$base.tar.gz.sha256" || { echo "Error: could not download uv from github.com (is the network blocked?)." >&2; rm -rf "$tmp"; return 1; }
  ( cd "$tmp" && printf '%s  uv.tar.gz\n' "$(cut -d' ' -f1 uv.sha256)" | sha256sum -c --status - 2>/dev/null || printf '%s  uv.tar.gz\n' "$(cut -d' ' -f1 uv.sha256)" | shasum -a 256 -c --status - ) || { echo "Error: the uv download failed its checksum; not using it." >&2; rm -rf "$tmp"; return 1; }
  mkdir -p "$dest" && tar -xzf "$tmp/uv.tar.gz" -C "$dest" --strip-components=1 && rm -rf "$tmp"
  [ -x "$dest/uv" ]
}
# ---- END install_uv

# ---- which system is this, and what does that mean for Python and PostgreSQL?
OS_ID="" OS_VER="" OS_CODENAME="" OS_NAME="this system"
OSF="${VELORA_OS_RELEASE:-/etc/os-release}"
osrel() { sed -n "s/^$1=//p" "$OSF" | head -1 | tr -d "\"'"; }                    # read one value (the file is parsed, never executed)
if [ -r "$OSF" ]; then OS_ID="$(osrel ID)"; OS_VER="$(osrel VERSION_ID)"; OS_CODENAME="$(osrel VERSION_CODENAME)"; OS_NAME="$(osrel PRETTY_NAME)"; fi
NEED_PRIVATE_PYTHON=0 NEED_PGDG=0
case "$OS_ID-$OS_VER" in
  ubuntu-18.04)
    if [ "$ALLOW_EOL" = 0 ]; then
      echo "Error: $OS_NAME reached end of life in 2023 (it ships Python 3.6 and PostgreSQL 10), so Velora will not set up a production SERVER on it." >&2
      echo "       Upgrade first (sudo do-release-upgrade, to 20.04 and then 22.04), or use a newer server. For development on this machine use install-dev.sh." >&2
      echo "       To install here anyway at your own risk: add --allow-eol." >&2
      exit 1
    fi
    echo "WARNING: $OS_NAME is end of life. Installing anyway because of --allow-eol."; NEED_PRIVATE_PYTHON=1; NEED_PGDG=1;;
  ubuntu-20.04|debian-11) echo "Note: $OS_NAME ships an old Python and PostgreSQL; a private Python and the official PostgreSQL repository will be used."; NEED_PRIVATE_PYTHON=1; NEED_PGDG=1;;
  ubuntu-22.04|ubuntu-24.04|ubuntu-26.04|debian-12|debian-13) ;;
  *) echo "Note: $OS_NAME has not been checked with Velora. It needs Python 3.10+ and PostgreSQL 13+; this installer will tell you what it finds.";;
esac
[ "${VELORA_FORCE_PRIVATE_PYTHON:-0}" = 1 ] && NEED_PRIVATE_PYTHON=1
PG_PKG="postgresql postgresql-client"; [ "$NEED_PGDG" = 1 ] && PG_PKG="postgresql-$PG_VERSION postgresql-client-$PG_VERSION"

say "1/7 System packages"
run apt-get update -qq
BASE_PKGS="curl ca-certificates gnupg git sudo"                                          # sudo: for the day-to-day `sudo velora ...` and the service restart
# shellcheck disable=SC2086
run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $BASE_PKGS
if [ "$NEED_PGDG" = 1 ]; then
  # the official PostgreSQL apt repository (the system's own PostgreSQL is too old: Velora needs 13 or newer)
  [ -n "$OS_CODENAME" ] || { echo "Error: cannot tell this system's release name for the PostgreSQL repository." >&2; exit 1; }
  run install -d /usr/share/postgresql-common/pgdg
  run curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc
  if [ "$DRY" = 1 ]; then echo "+ write /etc/apt/sources.list.d/pgdg.list: deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $OS_CODENAME-pgdg main"
  else echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $OS_CODENAME-pgdg main" > /etc/apt/sources.list.d/pgdg.list; fi
  run apt-get update -qq
fi
PKGS="$PG_PKG"
[ "$NEED_PRIVATE_PYTHON" = 1 ] || PKGS="$PKGS python3 python3-venv python3-pip"
[ -n "$DOMAIN" ] && PKGS="$PKGS nginx"
[ -n "$DOMAIN" ] && [ "$NO_TLS" = 0 ] && PKGS="$PKGS certbot python3-certbot-nginx"
# shellcheck disable=SC2086
run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $PKGS
if [ "$DRY" = 0 ] && [ "$NEED_PRIVATE_PYTHON" = 0 ]; then
  # the system Python is used only if it is new enough; otherwise fall back to a private one (no PPA, no touching the system Python)
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Note: the system Python is older than 3.10: using a private Python instead."; NEED_PRIVATE_PYTHON=1; }
fi
if [ "$DRY" = 0 ]; then
  PGNUM="$(runuser -u postgres -- psql -Atc 'show server_version_num' 2>/dev/null || echo 0)"
  [ "${PGNUM:-0}" -ge 130000 ] || { echo "Error: PostgreSQL reports version number $PGNUM, but Velora needs 13 or newer." >&2; exit 1; }
fi

say "2/7 Service user and directories"
id velora >/dev/null 2>&1 || run useradd --system --create-home --home-dir "$ROOT" --shell /bin/bash velora
run mkdir -p "$ROOT"
run chown velora:velora "$ROOT"

say "3/7 Velora (virtualenv)"
if [ "$NEED_PRIVATE_PYTHON" = 1 ]; then
  if [ "$DRY" = 1 ]; then
    echo "+ download uv (verified checksum) into $ROOT/tools, then: uv python install $PY_VERSION  (kept in $ROOT/python, separate from the system Python)"
    echo "+ runuser -u velora -- uv venv --seed --python $PY_VERSION $ROOT/venv"
  elif [ ! -x "$ROOT/venv/bin/velora" ]; then
    install_uv "$ROOT/tools" || exit 1
    chown -R velora:velora "$ROOT/tools"
    runuser -u velora -- env UV_PYTHON_INSTALL_DIR="$ROOT/python" "$ROOT/tools/uv" python install "$PY_VERSION"
    runuser -u velora -- env UV_PYTHON_INSTALL_DIR="$ROOT/python" "$ROOT/tools/uv" venv --seed --python "$PY_VERSION" "$ROOT/venv"
  fi
else
  [ -x "$ROOT/venv/bin/velora" ] || run runuser -u velora -- python3 -m venv "$ROOT/venv"
fi
run runuser -u velora -- "$ROOT/venv/bin/pip" install -q --upgrade pip
run runuser -u velora -- "$ROOT/venv/bin/pip" install -q --upgrade "$SOURCE" "psycopg[binary]"

say "4/7 PostgreSQL access for Velora"
DBPASS_FILE="$ROOT/.db-root-password"
if [ ! -f "$DBPASS_FILE" ]; then
  if [ "$DRY" = 1 ]; then echo "+ create PostgreSQL role 'velora_root' (CREATEDB CREATEROLE, createrole_self_grant on PostgreSQL 16+) with a random password in $DBPASS_FILE (mode 600)"
  else
    PW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
    runuser -u postgres -- psql -qc "CREATE ROLE velora_root LOGIN CREATEDB CREATEROLE PASSWORD '$PW'" 2>/dev/null ||
      runuser -u postgres -- psql -qc "ALTER ROLE velora_root PASSWORD '$PW'"
    # PostgreSQL 16+: a role that creates roles no longer gets to USE them unless told to, and Velora creates one role + database per company
    if [ "$(runuser -u postgres -- psql -Atc 'show server_version_num')" -ge 160000 ]; then
      runuser -u postgres -- psql -qc "ALTER ROLE velora_root SET createrole_self_grant = 'set, inherit'"
    fi
    install -m 600 -o velora -g velora /dev/null "$DBPASS_FILE"; printf '%s' "$PW" > "$DBPASS_FILE"
  fi
fi

say "5/7 First company and administrator (velora quickstart)"
if [ -f "$ROOT/workspace/platform/control_plane.json" ]; then
  echo "Already set up - skipping (re-run is safe)."
else
  if [ "$DRY" = 1 ]; then
    echo "+ runuser -u velora -- env VELORA_DB_ROOT_PASSWORD=<generated> $ROOT/venv/bin/velora quickstart $ROOT/workspace --email $EMAIL --company '$COMPANY' --no-sample --no-start --db postgres --db-root-user velora_root  (output saved to $ROOT/first-run.txt, mode 600)"
  else
    install -m 600 -o velora -g velora /dev/null "$ROOT/first-run.txt"        # private BEFORE the generated password is written to it
    runuser -u velora -- env VELORA_DB_ROOT_PASSWORD="$(cat "$DBPASS_FILE")" \
      "$ROOT/venv/bin/velora" quickstart "$ROOT/workspace" --email "$EMAIL" --company "$COMPANY" --no-sample --no-start \
      --db postgres --db-root-user velora_root | tee "$ROOT/first-run.txt"
  fi
fi

# Remember the PostgreSQL administrator login so creating companies from the Desk needs no password (safe to repeat)
if [ "$DRY" = 1 ]; then
  echo "+ velora pg admin-set --user velora_root --password-file $DBPASS_FILE   (so the Desk can create and drop companies)"
elif [ -f "$ROOT/workspace/platform/control_plane.json" ]; then
  runuser -u velora -- env VELORA_WORKSPACE="$ROOT/workspace" "$ROOT/venv/bin/velora" pg admin-set --user velora_root --password-file "$DBPASS_FILE" || true
fi

if [ -n "$EXTRAS" ]; then
  # optional packages (pdf, data, ml, forecast, markets, sftp, security, or all) - see `velora deps list`. Done AFTER the workspace exists so they are
  # remembered there and `velora update` keeps them current.
  # shellcheck disable=SC2086
  run runuser -u velora -- env VELORA_WORKSPACE="$ROOT/workspace" "$ROOT/venv/bin/velora" deps install ${EXTRAS//,/ } --yes
fi

say "6/7 Service (systemd), the velora command and update settings"
UNIT=/etc/systemd/system/velora.service
if [ "$DRY" = 1 ]; then
  echo "+ write $UNIT (ONE service: the web server and its background worker), /etc/sudoers.d/velora, /usr/local/bin/velora (works from anywhere), /usr/local/sbin/velora-domain (for \`sudo velora domain add\`) and update.restart_command"
  [ -z "$AUTO" ] || echo "+ write velora-update.service and velora-update.timer ($AUTO): runs 'velora update --yes', which backs up first and rolls back if anything fails"
else
cat > "$UNIT" <<UNITEOF
[Unit]
Description=Velora (web server + background worker)
After=network.target postgresql.service
[Service]
User=velora
WorkingDirectory=$ROOT/workspace
ExecStart=$ROOT/venv/bin/velora start --host 127.0.0.1 --port $PORT
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
UNITEOF
# The one thing the unprivileged velora user may do as root besides restarting itself: set up a company's web address (validated strictly by the helper).
cat > /usr/local/sbin/velora-domain <<'DOMAINHELPER'
#!/usr/bin/env bash
# velora-domain: the small ROOT helper behind `velora domain add|remove`. Installed by install.sh into /usr/local/sbin and allowed (only this file) in sudoers.
#
#   velora-domain add DOMAIN [--port 8000] [--no-tls] [--email you@example.com] [--dry-run]
#   velora-domain remove DOMAIN [--dry-run]
#
# It runs as root on behalf of the unprivileged velora user, so it trusts NOTHING it is given: every value is validated before it is used.
set -euo pipefail

usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
ACTION="${1:-}"; DOMAIN="${2:-}"; [ $# -ge 2 ] && shift 2 || { [ "$ACTION" = "-h" ] && usage 0; usage 2; }
PORT=8000 TLS=1 EMAIL="" DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:-}"; shift 2;;
    --no-tls) TLS=0; shift;;
    --email) EMAIL="${2:-}"; shift 2;;
    --dry-run) DRY=1; shift;;
    *) echo "Unknown option: $1" >&2; exit 2;;
  esac
done

[[ "$ACTION" =~ ^(add|remove)$ ]] || { echo "Error: action must be add or remove." >&2; exit 2; }
[ "${#DOMAIN}" -le 253 ] && [[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ ]] || { echo "Error: '$DOMAIN' is not a valid domain name." >&2; exit 2; }
[[ "$PORT" =~ ^[0-9]{2,5}$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || { echo "Error: invalid port." >&2; exit 2; }
[ -z "$EMAIL" ] || [[ "$EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || { echo "Error: invalid email." >&2; exit 2; }
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "Error: must run as root (it is meant to be called through sudo by velora)." >&2; exit 1; }

SITE="/etc/nginx/sites-available/velora-$DOMAIN"; LINK="/etc/nginx/sites-enabled/velora-$DOMAIN"
run() { if [ "$DRY" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }

if [ "$ACTION" = "remove" ]; then
  run rm -f "$LINK" "$SITE"
  if [ "$DRY" = 1 ]; then echo "+ nginx -t && systemctl reload nginx"; else nginx -t >/dev/null 2>&1 && systemctl reload nginx || true; fi
  echo "Removed the web-server site for $DOMAIN (its certificate, if any, is kept)."
  exit 0
fi

CONF="server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 50m;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location /api/events {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}"
if [ "$DRY" = 1 ]; then
  echo "+ write $SITE"; printf '%s\n' "$CONF" | sed 's/^/    | /'
  echo "+ ln -sf $SITE $LINK"; echo "+ nginx -t && systemctl reload nginx"
  if [ "$TLS" = 1 ]; then
    if [ -n "$EMAIL" ]; then WHO="-m $EMAIL"; else WHO="--register-unsafely-without-email"; fi
    echo "+ certbot --nginx -d $DOMAIN --non-interactive --agree-tos $WHO --redirect"
  fi
  exit 0
fi
command -v nginx >/dev/null || { echo "Error: nginx is not installed (re-run install.sh with --domain, or apt install nginx)." >&2; exit 1; }
printf '%s\n' "$CONF" > "$SITE"
ln -sf "$SITE" "$LINK"
if ! nginx -t >/dev/null 2>&1; then rm -f "$LINK" "$SITE"; echo "Error: nginx rejected the configuration; nothing was changed." >&2; exit 1; fi
systemctl reload nginx
if [ "$TLS" = 1 ]; then
  command -v certbot >/dev/null || { rm -f "$LINK" "$SITE"; systemctl reload nginx; echo "Error: certbot is not installed (apt install certbot python3-certbot-nginx)." >&2; exit 1; }
  if [ -n "$EMAIL" ]; then MAIL=(-m "$EMAIL"); else MAIL=(--register-unsafely-without-email); fi
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos "${MAIL[@]}" --redirect || { rm -f "$LINK" "$SITE"; systemctl reload nginx; echo "Error: could not get a certificate for $DOMAIN (is its DNS pointing at this server, and port 80 open?). Nothing was changed." >&2; exit 3; }
fi
echo "OK: $DOMAIN is served."
DOMAINHELPER
chmod 755 /usr/local/sbin/velora-domain
printf '%s\n' 'velora ALL=(root) NOPASSWD: /bin/systemctl restart velora' 'velora ALL=(root) NOPASSWD: /usr/local/sbin/velora-domain' > /etc/sudoers.d/velora
chmod 440 /etc/sudoers.d/velora
cat > /usr/local/bin/velora <<WRAPEOF
#!/bin/sh
# Runs velora as the service user, inside the workspace, from any directory:   sudo velora update   |   sudo velora doctor   |   sudo velora install-app <app>
export VELORA_WORKSPACE="$ROOT/workspace"
if [ "\$(id -un)" = velora ]; then exec "$ROOT/venv/bin/velora" "\$@"; fi
if [ "\$(id -u)" = 0 ]; then exec runuser -u velora -- env VELORA_WORKSPACE="$ROOT/workspace" "$ROOT/venv/bin/velora" "\$@"; fi
exec sudo -u velora env VELORA_WORKSPACE="$ROOT/workspace" "$ROOT/venv/bin/velora" "\$@"
WRAPEOF
chmod 755 /usr/local/bin/velora
runuser -u velora -- "$ROOT/venv/bin/python" - <<CONFIGEND
from velora.workspace import Workspace
ws = Workspace("$ROOT/workspace")           # Velora knows where its own settings live (in this version, and in older workspaces): never a hard-coded path
c = ws.common_config()
ws.update_config(
    update={**c.get("update", {}), "restart_command": "sudo -n /bin/systemctl restart velora", "framework_source": "$SOURCE"},
    domain={**c.get("domain", {}), "helper": "sudo -n /usr/local/sbin/velora-domain", "port": $PORT, "email": "$EMAIL"},
    auto_upgrade=c.get("auto_upgrade", True))
CONFIGEND
if [ -n "$AUTO" ]; then
cat > /etc/systemd/system/velora-update.service <<UPDATEEND
[Unit]
Description=Velora automatic update (backs up first; rolls back by itself if anything fails)
[Service]
Type=oneshot
User=velora
WorkingDirectory=$ROOT/workspace
ExecStart=$ROOT/venv/bin/velora update --yes
UPDATEEND
cat > /etc/systemd/system/velora-update.timer <<TIMEREND
[Unit]
Description=Velora automatic update ($AUTO)
[Timer]
OnCalendar=$AUTO
RandomizedDelaySec=1h
Persistent=true
[Install]
WantedBy=timers.target
TIMEREND
fi
systemctl daemon-reload
systemctl enable velora >/dev/null
systemctl restart velora                           # (re-)starts onto the code just installed; the server upgrades databases itself on start
[ -z "$AUTO" ] || systemctl enable --now velora-update.timer
fi

say "7/7 Web server"
if [ -n "$DOMAIN" ]; then
  if [ "$DRY" = 1 ]; then echo "+ nginx site for $DOMAIN -> 127.0.0.1:$PORT$( [ "$NO_TLS" = 0 ] && echo ' + certbot --nginx')"; else
cat > /etc/nginx/sites-available/velora <<NGEOF
server {
  listen 80;
  server_name $DOMAIN;
  client_max_body_size 50m;
  location / {
    proxy_pass http://127.0.0.1:$PORT;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 120s;
  }
}
NGEOF
    ln -sf /etc/nginx/sites-available/velora /etc/nginx/sites-enabled/velora
    nginx -t && systemctl reload nginx
    [ "$NO_TLS" = 1 ] || certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --no-eff-email --redirect -n
  fi
  URL="https://$DOMAIN"; [ "$NO_TLS" = 1 ] && URL="http://$DOMAIN"
else
  echo "No --domain given: Velora listens on 127.0.0.1:$PORT only (put your own proxy in front, or re-run with --domain)."
  URL="http://127.0.0.1:$PORT"
fi

say "Done"
echo "Open:      $URL"
echo "Sign in:   $EMAIL   (the password is in $ROOT/first-run.txt - save it, then delete that file)"
echo "Update:    sudo velora update          (fetches new code, backs up, upgrades every company, restarts; undoes it all if anything fails)"
echo "Domain:    sudo velora domain add erp.yourcompany.com        (a company's own web address + HTTPS, in one step)"
echo "Add app:   sudo velora install-app <name | git URL | folder>      Remove: sudo velora uninstall-app <name>"
echo "Check:     sudo velora doctor"
[ -z "$AUTO" ] || echo "Automatic: updates run $AUTO by themselves (stop with: sudo systemctl disable --now velora-update.timer)"
if [ -n "$DOMAIN" ]; then TUTORIAL_URL="https://$DOMAIN"; else TUTORIAL_URL="http://localhost:$PORT"; fi
echo "Tutorial:  $TUTORIAL_URL/tutorial      (a welcome page explaining what was set up opens at your first sign-in)"
echo "Remove:    sudo bash uninstall.sh      (keeps your data unless you add --purge)"
echo "Back up:   $ROOT/workspace/backups/ and platform/master.key - keep the key SEPARATELY from the databases"
