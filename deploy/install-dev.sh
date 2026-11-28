#!/usr/bin/env bash
# Velora installer for a DEVELOPER's computer (any Linux or macOS, any Ubuntu from 18.04): no root, no system changes, one command.
#
#   bash install-dev.sh --workspace ~/my-erp --email you@company.com      <- ONE command: install, create everything, and start it
#   bash install-dev.sh [--source PIP_SPEC_OR_WHEEL] [--dir ~/.velora] [--python 3.12] [--extras pdf,data] [--dry-run]
#   (with --workspace: also --email, --company "Name", --no-start)
#
# It downloads a private Python (so the system Python can be as old as it likes), makes a virtual environment in ~/.velora, installs Velora into it,
# and puts a `velora` command in ~/.local/bin. With --workspace it then runs `velora quickstart` for you (a working system on SQLite, started).
# Without it, run `velora quickstart` yourself afterwards. For production use install.sh on a server.
set -euo pipefail

SOURCE="velora" DIR="$HOME/.velora" PYV="3.12" EXTRAS="" DRY=0 WORKSPACE="" EMAIL="" COMPANY="" NO_START=0
usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --source) SOURCE="${2:?}"; shift 2;;
    --dir) DIR="${2:?}"; shift 2;;
    --python) PYV="${2:?}"; shift 2;;
    --extras) EXTRAS="${2:?}"; shift 2;;
    --workspace) WORKSPACE="${2:?}"; shift 2;;
    --email) EMAIL="${2:?}"; shift 2;;
    --company) COMPANY="${2:?}"; shift 2;;
    --no-start) NO_START=1; shift;;
    --dry-run) DRY=1; shift;;
    -h|--help) usage 0;;
    *) echo "Unknown option: $1" >&2; usage 2;;
  esac
done
[[ "$PYV" =~ ^3\.(1[0-9])$ ]] || { echo "Error: --python must be 3.10 to 3.19 (default 3.12)." >&2; exit 2; }
[ -z "$WORKSPACE" ] || [ -n "$EMAIL" ] || { echo "Error: --workspace needs --email (the administrator's address)." >&2; exit 2; }
[ -n "$WORKSPACE" ] || { [ -z "$EMAIL$COMPANY" ] && [ "$NO_START" = 0 ]; } || { echo "Error: --email, --company and --no-start only apply with --workspace." >&2; exit 2; }
[[ "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || [ -z "$EMAIL" ] || { echo "Error: '$EMAIL' is not an email address." >&2; exit 2; }
[[ "$EXTRAS" =~ ^[a-z,]*$ ]] || { echo "Error: --extras is a comma-separated list like pdf,data." >&2; exit 2; }
say() { printf '\n==> %s\n' "$*"; }
command -v curl >/dev/null || { echo "Error: curl is needed (sudo apt install curl)." >&2; exit 1; }
command -v tar >/dev/null || { echo "Error: tar is needed." >&2; exit 1; }

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

say "Installing Velora for development into $DIR"
BIN="$HOME/.local/bin"
if [ "$DRY" = 1 ]; then
  echo "+ download uv (verified checksum) into $DIR/tools"
  echo "+ uv python install $PYV            (a private Python in $DIR/python: your system Python is not touched)"
  echo "+ uv venv --seed --python $PYV $DIR/venv"
  echo "+ uv pip install $SOURCE${EXTRAS:+ (extras: $EXTRAS)}"
  echo "+ ln -sf $DIR/venv/bin/velora $BIN/velora"
  if [ -n "$WORKSPACE" ]; then
    echo "+ velora quickstart $WORKSPACE --email $EMAIL${COMPANY:+ --company \"$COMPANY\"}${NO_START:+}$([ "$NO_START" = 1 ] && echo " --no-start")    (creates the workspace, a company and the administrator, then starts it)"
  else
    echo "Next: velora quickstart"
  fi
  exit 0
fi
mkdir -p "$DIR" "$BIN"
[ -x "$DIR/tools/uv" ] || install_uv "$DIR/tools" || exit 1
export UV_PYTHON_INSTALL_DIR="$DIR/python"
"$DIR/tools/uv" python install "$PYV"
[ -x "$DIR/venv/bin/python" ] || "$DIR/tools/uv" venv --seed --python "$PYV" "$DIR/venv"
SPEC="$SOURCE"; [ -n "$EXTRAS" ] && [ "$SOURCE" = "velora" ] && SPEC="velora[$EXTRAS]"
"$DIR/tools/uv" pip install --python "$DIR/venv/bin/python" --upgrade "$SPEC" "psycopg[binary]"
[ -z "$EXTRAS" ] || [ "$SOURCE" = "velora" ] || "$DIR/venv/bin/velora" deps install ${EXTRAS//,/ } --yes
ln -sf "$DIR/venv/bin/velora" "$BIN/velora"

say "Done: $("$DIR/venv/bin/velora" --version)  (Python $("$DIR/venv/bin/python" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'))"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Add this to your shell profile so the command is found:   export PATH=\"$BIN:\$PATH\"" ;; esac
if [ -n "$WORKSPACE" ]; then
  say "Creating your workspace in $WORKSPACE"
  QS=("$DIR/venv/bin/velora" quickstart "$WORKSPACE" --email "$EMAIL")
  [ -z "$COMPANY" ] || QS+=(--company "$COMPANY")
  [ "$NO_START" = 0 ] || QS+=(--no-start)
  exec "${QS[@]}"                                  # prints the address, the sign-in and the one-time password, then runs the server
fi
echo "Next:      velora quickstart        (a working system on SQLite, with notifications and search; add --email you@company.com)"
echo "Tutorial:  open http://localhost:8000/tutorial once it is running; velora doctor checks the installation."
