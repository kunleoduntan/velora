"""docs/commands.md: the complete command reference, GENERATED.

Every command, sub-command, argument, option, default and help text comes from the real argument parser, so the flags it lists are exactly the ones the program accepts. What the
parser cannot know (what a command is FOR, what it does behind the scenes, examples) is written once below in NOTES. A test fails if a command has no explanation, if an example does not
parse, or if the committed page differs from what this module generates:

    python -m velora.cli_docs docs/commands.md
"""
from __future__ import annotations

import argparse
import sys

GROUPS = (
    ("Start here", ("quickstart", "start", "serve", "doctor", "layout")),
    ("Update, upgrade and recover", ("update", "upgrade", "upgrade-plan", "restore", "maintenance")),
    ("Back up and monitor (`velora ops ...`)", ("ops", "backup", "pg", "readiness", "manifest", "worker")),
    ("Companies, people and access", ("platform", "tenant", "company", "user", "domain")),
    ("Apps", ("new-app", "new-doctype", "new-doctypes", "get-app", "list-apps", "validate-app", "export-app", "import-app-package", "marketplace", "deploy", "install-app", "uninstall-app", "deps")),
    ("Data", ("import-data", "export-data", "import-template", "migrate", "doctypes")),
    ("Older one-database-per-site mode", ("init", "new-site", "drop-site", "list-sites", "use")),
)

# command path -> (what it is for and what it does, [examples])
NOTES: dict[str, tuple[str, list[str]]] = {
    "quickstart": ("Everything, in one step: creates the workspace folder, the control plane (sign-in and companies), a first company with its own database, a sample app and the administrator, then starts "
                   "the server. If you do not give a password, one is generated and shown once. SQLite by default (for trying things out); use `--db postgres` for real use. Safe to run again in the same folder.",
                   ["velora quickstart my-erp --email you@company.com", "velora quickstart my-erp --email you@company.com --company \"Acme Ltd\" --no-start",
                    "velora quickstart my-erp --email you@company.com --db postgres --db-root-password SECRET"]),
    "start": ("Runs the web server and the Desk (the browser interface), with the background worker (notifications, reminders, scheduled jobs) inside it. Each time it starts it also tidies the folder "
              "layout, repairs permissions and upgrades any database that is behind the installed code, so there is nothing else to remember. Behind a web server use the default host (127.0.0.1).",
              ["velora start", "velora start --host 0.0.0.0 --port 8080", "velora start --no-worker"]),
    "serve": ("The same as `velora start` (an alias).", ["velora serve --port 8000"]),
    "doctor": ("Checks the whole installation (Python, operating system, PostgreSQL, folder layout, databases, worker, backups) and says how to fix anything wrong. Exit code 1 if something failed.", ["velora doctor"]),
    "layout": ("Shows the folder structure of this workspace with real sizes, and anything that needs attention (loose permissions, an older layout awaiting its move). `--fix` repairs: older settings files "
               "are moved to `config/`, secrets become owner-only, the README and `.gitignore` are refreshed (only if you have not edited them). Exit code 1 if a warning remains.",
               ["velora layout", "velora layout --fix"]),
    "update": ("Gets new versions and applies them in one step: new code for apps (from git) and for Velora (from pip, a wheel or git), a backup, the database upgrade on the NEW code, then a restart. "
               "If anything fails everything is rolled back. `--check` only lists what is available.",
               ["velora update --check", "velora update --yes", "velora update --framework-source git+ssh://git@github.com/YOUR-USER/velora.git@main --yes"]),
    "upgrade": ("Upgrades the databases to the code that is installed (migrations and patches), with a backup first and automatic rollback. Use `velora update` to fetch new code as well. "
                "`--dry-run` shows the plan without changing anything.", ["velora upgrade --dry-run", "velora upgrade --yes", "velora upgrade --only COMP-001"]),
    "upgrade-plan": ("Shows what `velora upgrade` WOULD change (schema and patches) without touching any database, and writes a fingerprinted plan file you can review. Pass that file to `velora upgrade --plan-file` to require that nothing changed since you reviewed it.",
                     ["velora upgrade-plan", "velora upgrade-plan --only COMP-001 --out plan.json"]),
    "marketplace": ("Trusted local repositories of validated app packages (ZIP files). Add a folder as a source, list sources, and import a package from one, optionally checking its SHA-256 digest. Importing adds the app to the workspace; it does not install it.",
                    ["velora marketplace list", "velora marketplace add-source team /srv/packages", "velora marketplace import team my-app.zip --sha256 DIGEST"]),
    "deploy": ("Promotes validated apps from one workspace to another (for example staging to production). Create a profile with the source and target, preview with `plan`, then `promote`; databases are backed up first.",
               ["velora deploy profile-create prod --source /srv/staging --target /srv/prod", "velora deploy plan prod --app my-app", "velora deploy promote prod --app my-app --yes"]),
    "restore": ("Restores ONE database from a backup file (atomic: all or nothing; a safety copy of the current database is taken first unless told otherwise). For the whole workspace on a new machine "
                "use `velora ops restore-workspace`.", ["velora restore backups/20261111-COMP-001-database.sqlite.gz --company COMP-001 --yes"]),
    "maintenance": ("Turns maintenance mode on or off: the API answers 503 and the Desk shows an upgrading page. Updates do this automatically.", ["velora maintenance on --message \"Back at 18:00\"", "velora maintenance off", "velora maintenance status"]),
    "ops": ("Workspace health, encrypted backups, recovery rehearsals, alerts and metrics. The first word after `ops` is the action (table below). Backups are encrypted with a password: give it at the prompt, "
            "or in the environment variable VELORA_BACKUP_PASSWORD for cron and services.",
            ["velora ops status", "velora ops backup", "velora ops backup --no-files", "velora ops verify backups/workspace-20261111T100000Z.vbackup",
             "velora ops restore-workspace backups/workspace-20261111T100000Z.vbackup --into ~/my-erp-restored", "velora ops configure --every-hours 24 --keep 14", "velora ops run-scheduled",
             "velora ops metrics --format prometheus --out metrics.prom", "velora ops alerts"]),
    "backup": ("Backs up the database of a company (or a site) to a compressed file in `backups/`. With `--all`, every company. For the whole workspace (apps, settings, keys, uploads) use `velora ops backup`.",
               ["velora --company COMP-001 backup", "velora backup --all"]),
    "pg": ("PostgreSQL: what this server offers (version, extensions) and how well it is set up; `optimize` applies the safe improvements.", ["velora pg status", "velora pg status --json", "velora pg optimize", "velora pg admin", "velora pg admin-set --user velora_root --password-file /srv/velora/.db-root-password"]),
    "readiness": ("Checks that the workspace is configured for production and says what is missing. Exit code 1 if it is not ready.", ["velora readiness"]),
    "manifest": ("Creates, or verifies, a deployment integrity manifest: hashes of the files that matter, with no credentials in it, so you can prove a server still runs exactly what you deployed.",
                 ["velora manifest create", "velora manifest verify"]),
    "worker": ("Runs the scheduled tasks for every company (notification delivery, reminders, scheduled jobs) on its own, without the web server. `velora start` already runs this inside the server; "
               "use it only for a separate worker process.", ["velora worker", "velora worker --once", "velora worker --interval 30"]),
    "platform": ("The control plane: central sign-in, tenants and companies. `init` creates it (quickstart does this for you), `status` reports it, `audit` lists its security audit trail.",
                 ["velora platform init --admin-email you@company.com", "velora platform status", "velora platform audit"]),
    "tenant": ("A tenant is a group that owns companies (for example a business group). Companies belong to a tenant.", ["velora tenant create \"Acme Group\"", "velora tenant list"]),
    "company": ("A company has its OWN database, apps, users and files: nothing is shared between companies. `create` provisions the database and installs the apps you name; `suspend` blocks access without "
                "deleting anything; `drop` removes it permanently (needs `--yes`).",
                ["velora company create \"Acme Ltd\" --tenant \"Acme Group\" --apps velora_notify,velora_search", "velora company list", "velora company suspend COMP-002", "velora company activate COMP-002"]),
    "user": ("People who can sign in, and which companies they can use and with which roles. Passwords are never printed; give one with `--password`, the VELORA_USER_PASSWORD variable, or let it be generated.",
             ["velora user create you@company.com --name \"Your Name\" --platform-admin", "velora user grant you@company.com COMP-001 --roles \"System Manager\"", "velora user list",
              "velora user set-password you@company.com", "velora user deactivate old.staff@company.com"]),
    "domain": ("Gives a company its own web address in one step: registers it, configures the web server (nginx) and HTTPS. `check` verifies the DNS, `list` shows the registered addresses, `remove` undoes it.",
               ["velora domain add erp.acme.com COMP-001", "velora domain check erp.acme.com", "velora domain list", "velora domain remove erp.acme.com"]),
    "new-app": ("Scaffolds a new app in `apps/NAME`: a Python package with `hooks.py` and a first module.", ["velora new-app accounting", "velora new-app accounting --title \"Accounting\""]),
    "new-doctype": ("Scaffolds one DocType in an app: the JSON definition, a controller and client scripts. `--submittable` adds the draft, submit, cancel life cycle; `--child` makes it a table inside another DocType.",
                    ["velora new-doctype \"Journal Entry\" --app accounting --submittable"]),
    "new-doctypes": ("Creates DocTypes in an app from a JSON file, either Velora's own format or a Frappe DocType export. `--dry-run` shows what would happen; `--on-conflict` decides what to do when one exists.",
                     ["velora new-doctypes accounting exported.json --dry-run", "velora new-doctypes accounting exported.json --module Accounts"]),
    "get-app": ("Clones an app from git into `apps/`. It does not install it: use `install-app`.", ["velora get-app https://github.com/YOUR-USER/myapp.git --branch main"]),
    "list-apps": ("Lists the apps in this workspace.", ["velora list-apps"]),
    "validate-app": ("Validates an app package WITHOUT running its code.", ["velora validate-app accounting"]),
    "export-app": ("Builds a verified, distributable ZIP of an app (with a manifest of hashes).", ["velora export-app accounting --output accounting.zip"]),
    "import-app-package": ("Validates a Velora app ZIP and adds it to this workspace. It rejects unsafe archives (paths that escape, links, undeclared files). It does not install the app.", ["velora import-app-package accounting.zip"]),
    "install-app": ("Installs an app on EVERY company in one step: fetches it (a name in `apps/`, or a git URL), installs its Python packages and required apps first, creates the tables, runs the app's install code and "
                    "restarts the server. A failure in one company is reported and does not stop the others.",
                    ["velora install-app accounting", "velora install-app https://github.com/YOUR-USER/governmentone.git --branch main"]),
    "uninstall-app": ("Removes an app from EVERY company in one step, after checking nothing else depends on it, and after a backup. The app's data is kept unless you say `--purge` (which needs the backup).",
                      ["velora uninstall-app accounting", "velora uninstall-app accounting --purge --yes"]),
    "deps": ("Optional Python packages (data analysis, PDF and QR codes, machine learning, SFTP ...), checked and installed by name.", ["velora deps list", "velora deps check pdf", "velora deps install pdf data"]),
    "import-data": ("Loads any DocType's data from an Excel, CSV or JSON file. Columns are matched by name in any order; child rows go on the lines under their document. `--dry-run` runs the real validation and "
                    "SAVES NOTHING. Modes: insert, update, upsert. `--atomic` imports all or nothing. See docs/data-import.md.",
                    ["velora import-data Customer customers.xlsx --dry-run", "velora import-data Customer customers.xlsx --report failed.csv", "velora import-data Customer changes.csv --mode update"]),
    "export-data": ("Exports a DocType's data as JSON, CSV or Excel in exactly the layout `import-data` reads, to move data between companies or servers.", ["velora export-data Customer --format json --out customers.json",
                    "velora export-data Customer --format csv --filters '[[\"status\",\"=\",\"Active\"]]'"]),
    "import-template": ("Writes a blank import file with the right headings (and, for Excel, an Instructions sheet).", ["velora import-template \"Sales Order\" --format xlsx"]),
    "migrate": ("Brings a database in line with the installed apps' DocTypes (tables and columns). Upgrades and `install-app` do this for you; use it directly when you are developing. `--dry-run` prints the plan.",
                ["velora migrate --dry-run", "velora migrate --all-companies"]),
    "doctypes": ("Lists a database's DocTypes.", ["velora --company COMP-001 doctypes"]),
    "init": ("Creates an empty workspace folder (the older step-by-step flow). `velora quickstart` does this and much more.", ["velora init my-erp"]),
    "new-site": ("Older mode: creates one site with its own database. New installations use companies instead.", ["velora new-site erp.local"]),
    "drop-site": ("Older mode: deletes a site (and its database if Velora created it).", ["velora drop-site erp.local --yes"]),
    "list-sites": ("Older mode: lists sites.", ["velora list-sites"]),
    "use": ("Older mode: sets the default site.", ["velora use erp.local"]),
}

OPS_ACTIONS = (
    ("status", "A health snapshot as JSON (disk space, logs, apps). Exit code 1 if it fails."),
    ("backup [PATH]", "An encrypted backup of the whole workspace: apps, settings, keys, the control plane and company databases (SQLite databases captured consistently), and uploaded files (left out, and the backup says so, above 1 GiB; `--no-files` leaves them out on purpose). PostgreSQL companies are not inside: use `velora backup`."),
    ("verify PATH", "Decrypts a backup and checks it: the archive reads end to end and every SQLite database inside passes its integrity check. Works on any machine, with or without a workspace."),
    ("restore-workspace PATH --into DIR", "Restores a workspace backup into a NEW folder on a machine that has nothing. Never overwrites; refuses unsafe archives; keys and uploads become owner-only."),
    ("prune [--keep N]", "Deletes all but the newest N workspace backups (default 14)."),
    ("configure", "Sets the backup policy: how often (`--every-hours`), how many to keep (`--keep`), whether to include a workspace snapshot, whether to verify. Then schedule `run-scheduled` with cron or systemd."),
    ("run-scheduled [--force]", "Runs the backups that are due (uses VELORA_BACKUP_PASSWORD). Exit code 1 if a backup failed."),
    ("backup-status", "When the last backups were made and whether the next one is due."),
    ("monitor", "A monitoring snapshot as JSON. Exit code 1 if it fails."),
    ("recovery-report", "How old the evidence of a working recovery is. Exit code 1 if it is stale or unknown."),
    ("rehearse PATH", "Proves a compressed company database backup can be restored, in a scratch location."),
    ("postgres-rehearse PATH [--database-url URL]", "Proves a PostgreSQL dump restores into a disposable database, checks the restored tables against the dump, and records the measured restore time."),
    ("recovery-assurance", "The recorded evidence of rehearsals (the measured recovery time; it does not measure how much data a disaster would lose)."),
    ("dashboard [--out FILE]", "Writes a static HTML operations dashboard."),
    ("serve-dashboard [--host H] [--port P]", "Serves a live operations dashboard (loopback only by default; protect it with VELORA_OPS_DASHBOARD_TOKEN if you expose it)."),
    ("alert-configure", "Creates or shows the alert policy."),
    ("alerts", "Evaluates the alerts. Exit code 1 if any is critical."),
    ("notify [--email A] [--webhook URL]", "Delivers the current alerts by email (VELORA_SMTP_* settings) or to an HTTPS webhook."),
    ("metrics [--format json|prometheus] [--out FILE]", "The metrics, as JSON or in Prometheus text format."),
)

ENVIRONMENT = (
    ("VELORA_WORKSPACE", "the workspace folder (instead of `--workspace` or finding it from the current folder)"),
    ("VELORA_SITE", "the default site (older mode)"),
    ("VELORA_MASTER_KEY", "the key that encrypts stored company database passwords; if unset it is kept in `platform/master.key`"),
    ("VELORA_BACKUP_PASSWORD", "the backup encryption password, for unattended `ops backup`, `verify`, `restore-workspace`, `run-scheduled`"),
    ("VELORA_ADMIN_PASSWORD / VELORA_USER_PASSWORD", "default password for `quickstart` / `user create` (otherwise generated and shown once)"),
    ("VELORA_DB_HOST, VELORA_DB_PORT, VELORA_DB_ROOT_USER, VELORA_DB_ROOT_PASSWORD, VELORA_DB_PASSWORD", "PostgreSQL connection defaults for provisioning"),
    ("VELORA_DB_URL, VELORA_APPS, VELORA_DEVELOPER_MODE", "library/development mode: a database URL, the apps to load, developer mode"),
    ("VELORA_MAX_BODY_MB", "largest request body the server accepts (default 8; uploads and data imports have their own higher limits)"),
    ("VELORA_FILE_ROOT", "where uploaded files are stored outside a workspace"),
    ("VELORA_SMTP_HOST/PORT/USER/PASSWORD/FROM", "outgoing email for alerts"),
    ("VELORA_INTEGRATION_MASTER_KEY", "encrypts webhook secrets"),
    ("VELORA_OPS_DASHBOARD_TOKEN, VELORA_POSTGRES_REHEARSAL_URL, VELORA_WEBHOOK_TOKEN, VELORA_FRONTEND_DIST", "operations dashboard token; the disposable PostgreSQL for restore rehearsals; alert webhook token; a custom Desk build folder"),
)


# ---- help text for arguments the parser declares without any (applied by `apply_help` when the parser is built, so `velora COMMAND --help` and the reference both have it) ----
GENERIC_HELP = {
    "--dry-run": "show what would happen without changing anything",
    "--yes": "do not ask for confirmation",
    "--no-backup": "skip the safety backup that is normally taken first (not recommended)",
    "--no-restart": "do not restart the server afterwards",
    "--partial": "keep going if one database fails; it stays 'upgrade pending'",
    "--force": "go ahead even if the safety checks object",
    "--report-file": "write the report, as JSON, to this file",
    "--db": "database engine: sqlite (to try things out) or postgres (for real use)",
    "--db-host": "PostgreSQL host",
    "--db-port": "PostgreSQL port",
    "--db-root-user": "PostgreSQL administrator that may create databases and users (or VELORA_DB_ROOT_USER)",
    "--db-root-password": "that administrator's password (or VELORA_DB_ROOT_PASSWORD)",
    "--db-name": "database name to use or create",
    "--db-user": "database user to use or create",
    "--db-password": "that user's password (or VELORA_DB_PASSWORD)",
    "--host": "address to listen on (127.0.0.1 = this machine only; 0.0.0.0 = every network)",
    "--port": "port to listen on",
    "--module": "module (folder) inside the app",
    "--format": "output format",
    "--out": "file to write (default: a name made from the DocType and the time)",
    "--limit": "most entries to show or export",
    "--json": "machine-readable (JSON) output",
}
PER_COMMAND_HELP = {
    ("init", "path"): "folder to create the workspace in",
    ("quickstart", "path"): "folder for the new workspace",
    ("quickstart", "--email"): "the administrator's email address (it is the sign-in)",
    ("quickstart", "--no-start"): "create everything but do not start the server",
    ("quickstart", "--port"): "port the server listens on",
    ("new-doctypes", "app"): "the app to add the DocTypes to",
    ("new-doctypes", "--module"): "module inside the app to put them in",
    ("new-doctypes", "--child"): "create them as child tables (rows inside another DocType)",
    ("new-doctypes", "--submittable"): "make them submittable (draft, submit, cancel)",
    ("new-doctypes", "--track-changes"): "keep a version history of every change",
    ("deps", "action"): "what to do with the optional packages",
    ("deps", "--dry-run"): "show what pip would install without installing",
    ("deps", "--upgrade"): "also upgrade packages that are already installed",
    ("deps", "--yes"): "install without asking",
    ("apply-update", "--partial"): "keep going if one database fails",
    ("apply-update", "--no-backup"): "skip the safety backup",
    ("apply-update", "--report-file"): "write the report, as JSON, to this file",
    ("import-data", "doctype"): "the DocType to import into",
    ("import-data", "file"): "the .xlsx, .csv or .json file to import",
    ("import-data", "--mode"): "insert (create new documents), update (change existing ones) or upsert (both)",
    ("import-data", "--dry-run"): "check the file with the real validation and save nothing",
    ("import-data", "--submit"): "submit submittable documents after creating them",
    ("import-data", "--date-format"): "how dates are written in the file: DMY (31/12/2026), MDY (12/31/2026) or YMD (2026-12-31)",
    ("import-data", "--max-rows"): "refuse a file with more documents than this",
    ("export-data", "doctype"): "the DocType to export",
    ("export-data", "--format"): "json, csv or xlsx (all can be imported again)",
    ("import-template", "doctype"): "the DocType to make a template for",
    ("import-template", "--format"): "xlsx (with an Instructions sheet) or csv",
    ("domain", "action"): "what to do with the address",
    ("domain", "target"): "the company id the address belongs to (for add)",
    ("domain", "--primary"): "make this the company's main address",
    ("domain", "--dry-run"): "show the steps without doing them",
    ("worker", "--interval"): "seconds to wait between runs",
    ("pg", "action"): "status (report), optimize (apply the safe improvements), admin (show which administrator login company create/drop will use) or admin-set (remember one)",
    ("ops", "action"): "what to do (see the table of actions below)",
    ("manifest", "action"): "create a manifest, or verify the current files against one",
    ("upgrade", "--no-backup"): "skip the safety backup taken before upgrading (not recommended)",
    ("update", "--no-apps"): "update Velora only, not the apps",
    ("restore", "file"): "the backup file to restore",
    ("restore", "--company"): "the company to restore it into",
    ("restore", "--control-plane"): "restore the control plane (sign-in and company list) instead of a company",
    ("restore", "--no-safety-backup"): "do not copy the current database aside before replacing it",
    ("maintenance", "state"): "on, off, or status",
    ("maintenance", "--message"): "text shown to people while maintenance is on",
    ("new-site", "name"): "the site's name",
    ("drop-site", "name"): "the site to delete",
    ("use", "name"): "the site to use by default",
    ("new-app", "name"): "the app's name (a valid Python name)",
    ("new-app", "--module"): "name of the app's first module",
    ("new-app", "--title"): "a human-readable title",
    ("new-doctype", "name"): "the DocType's name, for example \"Journal Entry\"",
    ("new-doctype", "--app"): "the app to put it in",
    ("new-doctype", "--submittable"): "make it submittable (draft, submit, cancel)",
    ("get-app", "url"): "the git URL of the app",
    ("get-app", "--name"): "the folder name to use under apps/",
    ("get-app", "--branch"): "the branch or tag to clone",
    ("validate-app", "app"): "the app to check (its folder name)",
    ("export-app", "app"): "the app to package (its folder name)",
    ("import-app-package", "package"): "path of the app ZIP",
    ("install-app", "--branch"): "branch or tag, when the app is fetched from git",
    ("uninstall-app", "app"): "the app to remove",
    ("uninstall-app", "--no-backup"): "skip the backup taken first (the app's data cannot then be purged)",
    ("migrate", "--dry-run"): "print the plan without changing the database",
    ("platform init", "--admin-email"): "email of the first platform administrator",
    ("platform audit", "--limit"): "how many audit entries to show",
    ("tenant create", "name"): "the tenant's name",
    ("company create", "name"): "the company's name",
    ("company create", "--tenant"): "the tenant that owns the company (create it first with `velora tenant create`)",
    ("company create", "--code"): "a short id for the company (default: generated, like COMP-001)",
    ("company suspend", "company"): "the company's id",
    ("company activate", "company"): "the company's id",
    ("company drop", "company"): "the company's id",
    ("company drop", "--yes"): "confirm the permanent removal",
    ("user create", "email"): "the person's email address (their sign-in)",
    ("user create", "--name"): "their full name",
    ("user create", "--platform-admin"): "make them an administrator of the whole platform",
    ("user create", "--password"): "their first password (or VELORA_USER_PASSWORD; generated and shown once if omitted)",
    ("user grant", "email"): "the person",
    ("user grant", "company"): "the company's id",
    ("user revoke", "email"): "the person",
    ("user revoke", "company"): "the company's id",
    ("user set-password", "email"): "the person",
    ("user set-password", "--password"): "the new password (prompted for if omitted)",
    ("user deactivate", "email"): "the person",
    ("user activate", "email"): "the person",
}


def _key(a):
    return max(a.option_strings, key=len) if a.option_strings else a.dest


def apply_help(parser, path: str = "") -> None:
    """Fill in help for every argument that has none (existing help is never replaced). Called once, when the parser is built."""
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sp in a.choices.items():
                apply_help(sp, f"{path} {name}".strip())
        elif a.dest != "help" and not a.help:
            text = PER_COMMAND_HELP.get((path, _key(a))) or GENERIC_HELP.get(_key(a))
            if text:
                a.help = text


def missing_help(parser=None, path: str = "") -> list[str]:
    """Arguments still without help (a test requires this to be empty)."""
    if parser is None:
        from .cli import _build_parser
        parser = _build_parser()
    out = []
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sp in a.choices.items():
                out += missing_help(sp, f"{path} {name}".strip())
        elif a.dest != "help" and not a.help:
            out.append(f"{path}: {_key(a)}")
    return out


def _subparsers(parser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def _helps(sub):
    return {c.dest: c.help for c in sub._choices_actions}


def _lines_for(path: str, parser: argparse.ArgumentParser, help_text: str | None, depth: int = 3) -> list[str]:
    """Markdown for one command or sub-command."""
    note, examples = NOTES.get(path, (None, []))
    out = [f"{'#' * depth} `velora {path}`", ""]
    if note:
        out += [note, ""]
    elif help_text:
        out += [help_text[0].upper() + help_text[1:] + ".", ""]
    usage = parser.format_usage().replace("usage: ", "").strip().replace("\n", " ")
    out += ["```", " ".join(usage.split()), "```", ""]
    positionals = [a for a in parser._actions if not a.option_strings and a.dest not in ("help",) and not isinstance(a, argparse._SubParsersAction)]
    options = [a for a in parser._actions if a.option_strings and a.dest != "help"]
    if positionals:
        out += ["| Argument | Meaning |", "|---|---|"]
        for a in positionals:
            choices = f" One of: {', '.join(map(str, a.choices))}." if a.choices else ""
            out.append(f"| `{a.dest}` | {(a.help or '').strip() or '(required)' if a.nargs not in ('?', '*') else (a.help or 'optional').strip()}{choices} |")
        out.append("")
    if options:
        out += ["| Option | Default | Meaning |", "|---|---|---|"]
        for a in options:
            if a.help == argparse.SUPPRESS:
                continue
            flag = " / ".join(f"`{o}`" for o in a.option_strings) + ("" if a.nargs == 0 else " VALUE")
            default = "" if a.default in (None, False, argparse.SUPPRESS) or a.nargs == 0 else f"`{a.default}`"
            out.append(f"| {flag} | {default} | {(a.help or '').strip()} |")
        out.append("")
    if examples:
        out += ["Examples:", "", "```bash"] + examples + ["```", ""]
    sub = _subparsers(parser)
    if sub is not None:
        helps = _helps(sub)
        for name, sp in sub.choices.items():
            out += _lines_for(f"{path} {name}", sp, helps.get(name), depth + 1)
    return out


def render() -> str:
    from .cli import _build_parser
    parser = _build_parser()
    sub = _subparsers(parser)
    helps = _helps(sub)
    commands = dict(sub.choices)
    grouped = {c for _, names in GROUPS for c in names}
    visible = {n for n in commands if helps.get(n) != argparse.SUPPRESS}                  # only the deliberately hidden (internal) commands are left out
    missing = sorted(visible - grouped)
    if missing:
        raise SystemExit(f"commands not in any group in velora/cli_docs.py: {missing}")
    out = ["<!-- Generated by `python -m velora.cli_docs docs/commands.md` from the real argument parser. Do not edit by hand: a test fails if this file differs. -->",
           "# Velora command reference", "",
           "Every command is `velora [GLOBAL OPTIONS] COMMAND [ARGUMENTS] [OPTIONS]`. Run `velora COMMAND --help` for the same information in the terminal.", "",
           "## Global options", "", "| Option | Meaning |", "|---|---|"]
    for a in parser._actions:
        if a.option_strings and a.dest != "help":
            out.append(f"| {' / '.join(f'`{o}`' for o in a.option_strings)} | {(a.help or '').strip()} |")
    out += ["", "Typical day to day: `velora start`, `velora doctor`, `velora ops backup`, `velora update`. Most commands find the workspace from the folder you are in, and the company when there is only one.", ""]
    for title, names in GROUPS:
        out += [f"## {title}", ""]
        for n in names:
            if n in commands:
                out += _lines_for(n, commands[n], helps.get(n))
        if title.startswith("Back up"):
            out += ["### `velora ops` actions", "", "| Action | What it does |", "|---|---|"] + [f"| `{a}` | {d} |" for a, d in OPS_ACTIONS] + [""]
    out += ["## Environment variables", "", "| Variable | Meaning |", "|---|---|"] + [f"| `{k}` | {v} |" for k, v in ENVIRONMENT] + [""]
    return "\n".join(out).rstrip() + "\n"


def examples() -> list[str]:
    return [e for _, ex in NOTES.values() for e in ex]


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "docs/commands.md"
    open(target, "w").write(render())
    print(f"Wrote {target}")
