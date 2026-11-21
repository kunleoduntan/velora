# Install, update, add apps, uninstall: one command each

Everything below is **one command that does every step itself**. You never run a second command first, never `cd` anywhere, and never restart anything by hand.

| You want to | Type | It does, by itself |
|---|---|---|
| **Install on a server** | `sudo bash install.sh --email you@co.com` | system packages, PostgreSQL, a `velora` user, a virtualenv, your first company (with notifications and search built in), **one** service (web server + background worker), a `velora` command that works from anywhere, optionally nginx + TLS |
| **Try it on a laptop** | `velora quickstart` | a working, signed-in system on SQLite (or `--db postgres`) |
| **Update** | `sudo velora update` | fetch new code, install the Python packages it needs, **back up**, upgrade every company's database, enable new built-in features, restart; **undoes everything if anything fails** |
| **Add an app** | `sudo velora install-app <name \| git URL \| folder>` | fetch it, install its Python packages, install the apps it needs first, install it on **every** company, restart |
| **Remove an app** | `sudo velora uninstall-app <name>` | back up, remove it from **every** company (data kept), restart |
| **Give a company its own address** | `sudo velora domain add erp.acme.com COMP-001` | check the name and DNS, register it for that company, write the nginx site, get the HTTPS certificate; **undoes itself if any step fails** |
| **Remove everything** | `sudo bash uninstall.sh` | final backup, then remove the service; your data stays unless you add `--purge` |

On a server, `velora` is a wrapper that runs as the service user inside the workspace, so `sudo velora update` works from any directory.

## Install
```bash
sudo bash install.sh --email you@company.com --company "My Company" \
     [--domain erp.example.com] [--extras pdf,data] [--auto-update daily] [--source <pip spec>]
```
Safe to re-run: a re-run upgrades the installation and restarts it onto the new code. `--extras` installs optional Python packages (see `extras.md`) and remembers them so updates keep them current. `--auto-update daily|weekly` is **opt-in** and runs `velora update --yes` on a timer (stop it with `sudo systemctl disable --now velora-update.timer`). There is only ever **one** service: the server starts its own background worker (notifications, reminders, scheduled jobs).

## Update
```bash
sudo velora update          # tell it where new releases come from ONCE:  --framework-source <pip spec | wheel folder | git URL>
sudo velora update --check  # only list what is available
```
Order of work: new code → packages → backup → data upgrade (on the **new** code, in a fresh process) → built-in features → restart. If anything fails, the code **and** the databases go back to exactly how they were. Maintenance mode is on for the duration, so users see an "upgrading" screen that reloads by itself.
`velora start` also upgrades any database that is behind the installed code **by itself, with a backup**, so even `pip install -U velora && restart` is safe (`--no-auto-upgrade` to turn that off).

## Add an app
```bash
sudo velora install-app inventory                         # an app already in the workspace, or a built-in one
sudo velora install-app https://github.com/you/hr-app.git # clone it first
sudo velora install-app ./my_app                          # a folder (copied in)
sudo velora --company COMP-001 install-app inventory      # only one company (default: all)
```
It installs the app's Python packages (`required_packages` in its `hooks.py`, plus its `pyproject.toml` dependencies) before touching any database, installs the apps it requires first, and carries on past a company that fails (that company is rolled back; the command exits 1 and says which). Run it again to retry. `--no-deps` refuses instead of installing packages; `--no-restart` skips the restart.

## Remove an app
```bash
sudo velora uninstall-app inventory                  # asks first (or --yes); data is KEPT; a backup is taken first
sudo velora uninstall-app inventory --purge --yes    # ALSO delete its data (always after a backup)
sudo velora uninstall-app inventory --remove-code    # ALSO delete its folder (refused while any company still has it)
```
Everything is checked **before** anything changes (for example another app needing it), and then nothing is changed anywhere. Reinstalling brings kept data straight back. **Removing a built-in app (notifications, search) is remembered**: `velora update` will not switch it back on.

## Remove everything
```bash
sudo bash uninstall.sh            # stops and removes the service; KEEPS /srv/velora and your databases
sudo bash uninstall.sh --purge    # after a final backup archive in /root: drops every company database, the role, the files and the user
```
PostgreSQL, nginx and Python themselves are never removed.

## Your own web address (domains)
```bash
velora domain check erp.acme.com           # is DNS pointing anywhere yet?
sudo velora domain add erp.acme.com COMP-001   # register + nginx + HTTPS (the company is optional when there is only one)
sudo velora domain list
sudo velora domain remove erp.acme.com
sudo velora domain add erp.acme.com COMP-001 --no-tls      # register without HTTPS (e.g. before DNS exists)
```
Create an `A` record for the address at your DNS provider first; without DNS the certificate cannot be issued, so the command stops and changes nothing. An address belongs to **one** company. By default it is **locked**: the sign-in screen offers only that company, the company is chosen from the address, and the address can never be used to reach another company (`--unlocked` allows switching). The company is decided from the `Host` header, which the generated nginx site passes through unchanged; live notifications are never buffered. On a server not installed with `install.sh` there is no web-server helper, so the command still registers the address and prints the exact nginx site to add yourself. The helper is a small, strictly validating root script that sudoers allows the `velora` user to run, and nothing else.

## The welcome page and the tutorial
Every install, update, upgrade, app change and address change is recorded in plain words. The first time you sign in after one, the Desk opens a **welcome page** that says exactly what happened (step by step, with failures marked), what is installed, how to start, and keeps a "What's new" history. The book icon in the header always reopens it. **"Open the full tutorial"** opens `/tutorial`: one self-contained HTML page (no internet needed, searchable, printable) that works without signing in, so it is also the thing to send a new colleague. The command line prints its address after install.

## Built-in features
New companies get **notifications** (`velora_notify`) and **global search** (`velora_search`) automatically, and `velora update` enables them on existing companies the first time. Settings (in `sites/common_site_config.json`):

| Key | Meaning |
|---|---|
| `default_apps` | apps every new company gets, and that `update` enables where missing (default `["velora_notify","velora_search"]`; set `[]` to opt out) |
| `default_apps_skip` | companies where you removed a default app on purpose (written for you) |
| `extras` | optional package groups you chose; `update` keeps them current (written by `velora deps install`) |
| `auto_upgrade` | `velora start` upgrades out-of-date databases itself (default on after install) |
| `update.framework_source` / `update.restart_command` | where releases come from / how to restart (the installer sets both) |

## How it fails safely
Backups come first for anything that can lose data (update, uninstall, purge, automatic upgrade). Every database change is all-or-nothing per company. `velora doctor` warns if no worker is running, a package is missing, or the PostgreSQL server needs attention.

## Honest limits
* `install.sh` and `uninstall.sh` are tested with `--dry-run`, shellcheck, and by their generated pieces; I have **not** run them on a real fresh server. The commands behind them were run for real with real wheels: `quickstart`, `install-app`, `update` (0.8.1 to 0.8.2) and `uninstall-app` on SQLite, and `quickstart` plus a running server (worker, live stream, inbox, search over HTTP) on PostgreSQL. Their PostgreSQL paths (install, uninstall, purge, update) are covered by automated tests that run against real PostgreSQL company databases.
* "Every company" is the default on purpose; use `--company` to limit it. A company that fails is reported and skipped, not hidden.
* Installing an app from git or a folder means trusting its code: it runs inside your server.
* `domain add` and its root helper have been tested with dry runs, shellcheck, hostile-input tests and a fake helper; I have **not** run them against a real nginx and Let's Encrypt. Try it on a spare name first.
* The welcome page and tutorial are tested, and the data behind them was exercised over HTTP against a real server, but the page has not been opened in a real browser.
* `update` fetches Velora and apps from the sources you configured; it never guesses a source. Velora itself is not on PyPI: give `--framework-source` once.
* Restart is a full restart of the one service (a few seconds); there is no zero-downtime rolling restart.


## Reviewed database upgrade plans (v0.56.0+)

Use `velora upgrade-plan` to inspect the schema operations, pending patches and warnings
for every selected target. The command writes a fingerprinted JSON plan and does not
change company databases:

```bash
velora upgrade-plan --out upgrade-plan.json
```

Review the plan with your deployment/change-control process, then execute only if the
live plan still matches:

```bash
velora upgrade --plan-file upgrade-plan.json
```

The command rejects a modified plan, a different workspace or code version, a changed
target selection, or any change in the live migration preview. A plan-file execution
requires the existing automatic backup path; `--no-backup` is deliberately rejected.
The fingerprint is an integrity check, not a digital signature or authorization token.
Keep plan files with deployment records and protect them from unauthorized modification.

## UI extension inventory (v0.57.0+)

Developer Studio displays the frontend assets and lifecycle hooks declared by installed
applications. Asset manifests include SHA-256 and byte size to support inspection and
deployment verification. The catalogue is read-only and does not install, enable or
execute application code.
