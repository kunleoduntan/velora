# Installing, updating and upgrading Velora

## Install in one command

```bash
pip install velora
velora quickstart                      # asks for an email and a company name, then opens a working system
```
`quickstart` creates a workspace, the control plane, your first company (with its own database), a sample app, and an administrator,
then starts the server. The password is generated and shown **once** (or pass `--password`). Add `--db postgres --db-root-password ...` for real use
(SQLite is for trying things out), `--no-sample`, `--no-start`, `--open` (opens the browser).

**On a server (Ubuntu/Debian):**
```bash
sudo bash deploy/install.sh --email you@company.com --company "My Company" --domain erp.example.com
```
Installs PostgreSQL, Velora in its own virtualenv, a systemd service, nginx and a Let's Encrypt certificate; configures `velora update` to restart the service. Safe to re-run. `--dry-run` prints every command without running anything.

`velora doctor` checks an installation (Python, packages, tools, disk, master key, every database, pending upgrades) and says how to fix each problem.

## Two commands to remember

| Command | What it does |
|---|---|
| `velora update` | **Fetch new code** (apps from git, Velora from pip), then run `velora upgrade`. Undoes the code if the upgrade fails. |
| `velora upgrade` | **Bring the data up to the installed code.** Use it alone after a Docker image swap, `pip install -U velora`, or a manual `git pull`. |

Both take `--dry-run` (show what would happen), `--partial`, `--no-backup` (not recommended). `velora update --check` lists available updates and exits **10** when there are some (for monitoring).
`velora update --framework-source` accepts a pip spec, a wheel file, a directory of wheels, or a git URL; set it once in `config/common.json`:
```json
{"update": {"framework_source": "velora", "restart_command": "sudo -n /bin/systemctl restart velora"}}
```

## What an upgrade does

```
lock → plan → maintenance ON → back up every database that needs it
     → control plane, then each company/site: pre-sync patches → schema sync → post-sync patches → version stamp
     → health check → maintenance OFF
```
* **Maintenance mode**: while it runs, the API answers `503` + `Retry-After`; the Desk shows an "Upgrading" screen that reloads by itself. `/api/health` returns 503 so a load balancer drains the node.
* **All-or-nothing**: if *any* database fails, every database already touched is restored from the backup taken seconds earlier (each restore is a single transaction on PostgreSQL), and `velora update` also puts the code back
  (`git reset --hard <previous commit>`, `pip install velora==<previous>`). The result is exactly the state you started from, plus a clear report of what failed and why.
  `--partial` instead leaves the failed company answering "upgrade pending" and upgrades the rest.
* **The version gate**: new code never runs against an old database. A database whose version is behind (new MAJOR.MINOR) answers `503 UpgradePending` until `velora upgrade` has run; a database *newer* than the code (a downgrade) is refused. Bug-fix releases (same MAJOR.MINOR) need no data upgrade.
* **A missing SQLite file is never silently recreated** as an empty database; the upgrade stops and tells you to restore it.
* Backups are kept in `backups/upgrade-<time>/` (the last 5 are kept) with a manifest; reports in `logs/upgrade-*.json`.
* One upgrade at a time (lock file, stale locks from crashed runs are detected).

## For app developers

**Version your app**: `__version__` in `<app>/__init__.py` (recorded per database), and optionally in `hooks.py`: `required_velora = ">=0.8,<0.9"` (an upgrade refuses an incompatible pairing with a clear message).

**Schema changes are automatic** when additive (new DocType, new field, new index). Safe widening (longer text field, Integer→BigInteger) is applied on PostgreSQL. Anything lossy (changing a field's kind, shrinking, dropping) is never applied silently:
it appears as a `WARNING` and you ship a **data patch**.

**Data patches** - `<app>/patches.txt`:
```
[pre_model_sync]            # before the schema is synced (rare)
myapp.patches.v2.rename_status
[post_model_sync]           # after (the default): backfill, convert
myapp.patches.v2.fill_defaults
```
Each module defines `execute()`. A patch runs **once per database**, in its own transaction together with its log entry (a failing patch changes nothing and is retried), and **inside the company it migrates**
(`velora.current_company()` works). Fresh installs record existing patches as done without running them.

## Hosting recipes

* **VPS (systemd)**: `install.sh` does everything; then `sudo -u velora /srv/velora/venv/bin/velora update` from `/srv/velora/workspace`.
* **Docker / image-based**: build a new image with the new code, roll it out, then run `velora upgrade` once (e.g. `docker compose exec velora velora upgrade`). The version gate keeps new containers from serving un-upgraded databases.
* **Managed PostgreSQL**: works; PostgreSQL client tools (`pg_dump`, `psql`) must be on the machine that runs `velora` for backups and automatic rollback.
* **Scheduled checks**: `velora update --check` in cron; alert on exit code 10. Apply during a quiet hour with `velora update`.

## Honest limits
* Not zero-downtime: users see the maintenance screen for the length of the upgrade (usually seconds to minutes).
* Rolling the *framework* back uses `pip install velora==<previous>` from the same source, so the previous version must still be obtainable there (keep old wheels). App code rolls back with git and always works.
* Automatic rollback needs backups: with `--no-backup` a failed upgrade is reported as **failed** (never "rolled back") and databases already upgraded stay upgraded.
* Restores need `psql` for PostgreSQL. The control plane is restored too, but `platform/master.key` is not backed up by Velora: keep a separate copy.
* App-supplied web assets/JS are served from the app code, so a Desk rebuild is only needed for framework releases (which ship the built Desk).
