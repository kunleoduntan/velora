"""`velora` command line.

Workspace workflow (the bench equivalent):

  velora init myworkspace                      create a workspace            (cd myworkspace)
  velora new-site erp.local                    create a site + its database
  velora new-app accounting                    scaffold an app
  velora new-doctype "Journal Entry" --app accounting
  velora --site erp.local install-app accounting
  velora start                                 serve every site in the workspace (Host header picks the site)

  velora get-app https://github.com/company/governmentone.git
  velora list-apps | list-sites | use <site> | migrate [--dry-run] | doctypes | backup | uninstall-app | drop-site

Outside a workspace the legacy single-site mode still works, configured by
VELORA_DB_URL / VELORA_APPS / VELORA_DEVELOPER_MODE.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading

import getpass
from pathlib import Path

from . import apps as apps_mod, provision, scaffold, site as site_mod
from .workspace import Workspace, WorkspaceError, resolve_desk_path


def _port(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a port number") from None
    if not 1 <= n <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return n


def _need_workspace(args) -> Workspace:
    ws = Workspace.discover(args.workspace)
    if ws is None:
        raise WorkspaceError("Not inside a Velora workspace. Run `velora init <dir>` first (or cd into one, or set VELORA_WORKSPACE).")
    ws.activate()
    return ws


def _plane(args, ws: Workspace):
    from .controlplane import ControlPlane
    plane = ControlPlane.open(ws)
    return plane


def _site(args, ws: Workspace) -> site_mod.Site:
    if getattr(args, "company", None):
        plane = _plane(args, ws)
        co = plane.registry.get_company(args.company)
        if co is None:
            raise WorkspaceError(f"No such company: {args.company}")
        return plane.router.site_for(co)
    try:
        name = ws.current_site(args.site)
    except WorkspaceError:
        if args.site is None and (ws.root / "platform" / "control_plane.json").exists():
            return _only_company_site(args, ws)               # a multi-company workspace with ONE company: no need to say which
        raise
    return site_mod.load_site(ws.site_path(name))


def _only_company_site(args, ws: Workspace) -> site_mod.Site:
    plane = _plane(args, ws)
    companies = [c for c in plane.registry.list_companies() if c.get("status", "active") == "active"]
    if len(companies) == 1:
        return plane.router.site_for(companies[0])
    if not companies:
        raise WorkspaceError("This workspace has no companies yet. Create one with `velora company create`.")
    ids = ", ".join(c["id"] for c in companies[:6])
    raise WorkspaceError(f"This workspace has {len(companies)} companies ({ids}). Choose one with --company ID.")


def _password(given: str | None, label: str = "Password") -> str:
    if given:
        return given
    if sys.stdin.isatty():
        first = getpass.getpass(f"{label}: ")
        if first != getpass.getpass(f"Repeat {label.lower()}: "):
            raise WorkspaceError("Passwords do not match")
        return first
    raise WorkspaceError(f"{label} required: pass --password, set the environment variable, or run interactively")


def _build_parser():
    p = argparse.ArgumentParser(prog="velora", description="Velora - metadata-driven business application platform", formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="""Everyday commands - each is ONE step, and does everything itself:
  velora quickstart              set up and start a working system (first company, notifications and search included)
  velora install-app APP         install an app (a name, git URL or folder) on every company: fetch, packages, install, restart
  velora update                  fetch new code, back up, upgrade every company, restart; undoes it all if anything fails
  velora uninstall-app APP       remove an app from every company (backs up first; --purge also deletes its data)
  velora import-data DOCTYPE FILE   load any DocType's data from Excel/CSV/JSON (--dry-run checks first); export-data moves it out again
  velora doctor                  check the installation and say how to fix anything wrong
On a server: install.sh installs everything in one command, uninstall.sh removes it.""")
    p.add_argument("--site", help="site to run the command against (default: VELORA_SITE, `velora use`, or the only site)")
    p.add_argument("--workspace", help="workspace directory (default: the nearest parent folder that contains config/apps.txt)")
    p.add_argument("--company", help="company id/code (platform mode) to run install-app / migrate / doctypes / backup against")
    sub = p.add_subparsers(dest="cmd", required=True)

    p.add_argument("--version", action="version", version=f"velora {__import__('velora').__version__}")
    sub.add_parser("init", help="create a workspace").add_argument("path")

    q = sub.add_parser("quickstart", help="one command from install to a running, signed-in system")
    q.add_argument("path", nargs="?", default="velora-workspace")
    q.add_argument("--email"); q.add_argument("--password", default=os.environ.get("VELORA_ADMIN_PASSWORD"), help="default: generated and shown once")
    q.add_argument("--company", help="your first company's name")
    q.add_argument("--no-sample", action="store_true", help="do not create the sample app")
    q.add_argument("--no-start", action="store_true"); q.add_argument("--open", action="store_true", help="open the browser")
    q.add_argument("--port", type=_port, default=8000)
    q.add_argument("--db", choices=["sqlite", "postgres"], default="sqlite")
    q.add_argument("--db-host", default="localhost"); q.add_argument("--db-port", type=int, default=5432)
    q.add_argument("--db-root-user", default="postgres"); q.add_argument("--db-root-password", default=os.environ.get("VELORA_DB_ROOT_PASSWORD"))

    nd = sub.add_parser("new-doctypes", help="create DocTypes in an app from JSON (Velora or a Frappe DocType export)")
    nd.add_argument("app"); nd.add_argument("file", help="a JSON file, or - for standard input")
    nd.add_argument("--module"); nd.add_argument("--name", help="the DocType name, when the JSON is only a list of fields")
    nd.add_argument("--child", action="store_true"); nd.add_argument("--submittable", action="store_true"); nd.add_argument("--track-changes", action="store_true")
    nd.add_argument("--autoname-field", help="name documents after this field")
    nd.add_argument("--on-conflict", choices=["error", "skip"], default="error", help="what to do with a DocType that already exists")
    nd.add_argument("--dry-run", action="store_true", help="validate and show what would be created, write nothing")

    dp = sub.add_parser("deps", help="optional Python packages (numpy, pandas, PDF/QR, ML, SFTP ...)")
    dp.add_argument("action", choices=["list", "check", "install"]); dp.add_argument("extras", nargs="*", help="e.g. pdf data ml (or: all)")
    dp.add_argument("--app", help="install the packages an app declares (required_packages in its hooks.py)")
    dp.add_argument("--dry-run", action="store_true"); dp.add_argument("--upgrade", action="store_true"); dp.add_argument("--yes", action="store_true")

    ap = sub.add_parser("apply-update", help=argparse.SUPPRESS)          # internal: run by `velora update` on the NEW code
    ap.add_argument("--partial", action="store_true"); ap.add_argument("--no-backup", action="store_true"); ap.add_argument("--report-file")

    di_ = sub.add_parser("import-data", help="import any DocType's data from an Excel, CSV or JSON file (Frappe-style); --dry-run checks without saving")
    di_.add_argument("doctype"); di_.add_argument("file")
    di_.add_argument("--mode", choices=["insert", "update", "upsert"], default="insert"); di_.add_argument("--dry-run", action="store_true"); di_.add_argument("--submit", action="store_true")
    di_.add_argument("--atomic", action="store_true", help="all or nothing: if any document fails, nothing is imported"); di_.add_argument("--keep-names", action="store_true", help="keep the IDs in the file (migration; System Manager)")
    di_.add_argument("--date-format", choices=["DMY", "MDY", "YMD"], default="DMY"); di_.add_argument("--match", help="update/upsert: find existing documents by this unique field instead of the ID")
    di_.add_argument("--report", help="write the failed rows (with the reason) to this CSV file"); di_.add_argument("--max-rows", type=int, default=200000)
    ex_ = sub.add_parser("export-data", help="export a DocType's data as JSON, CSV or Excel, in the layout import-data reads (for migrating between companies or servers)")
    ex_.add_argument("doctype"); ex_.add_argument("--format", choices=["json", "csv", "xlsx"], default="json"); ex_.add_argument("--out"); ex_.add_argument("--filters", help='JSON, e.g. [["status","=","Active"]]'); ex_.add_argument("--limit", type=int, default=50000)
    it_ = sub.add_parser("import-template", help="write a blank import file with the right headings")
    it_.add_argument("doctype"); it_.add_argument("--format", choices=["xlsx", "csv"], default="xlsx"); it_.add_argument("--out")

    ly = sub.add_parser("layout", help="show the folder structure of this workspace with real sizes, check permissions, and repair them (--fix)")
    ly.add_argument("--fix", action="store_true", help="apply the repairs: move old files into place, make secrets owner-only, refresh README and .gitignore")
    ly.add_argument("--write-docs", metavar="FILE", help="(maintainers) write the generated docs/file-structure.md")
    dm = sub.add_parser("domain", help="give a company its own web address, in one step (register + web server + HTTPS)")
    dm.add_argument("action", choices=["add", "list", "remove", "check"]); dm.add_argument("name", nargs="?", help="e.g. erp.acme.com"); dm.add_argument("target", nargs="?", metavar="COMPANY")
    dm.add_argument("--primary", action="store_true"); dm.add_argument("--unlocked", action="store_true", help="let people on this address reach the user's OTHER companies too")
    dm.add_argument("--no-tls", action="store_true", help="register without HTTPS"); dm.add_argument("--dry-run", action="store_true")

    wk = sub.add_parser("worker", help="run scheduled tasks for every company (notification delivery, reminders, ...)")
    wk.add_argument("--once", action="store_true", help="one pass, then exit"); wk.add_argument("--interval", type=float, default=5.0)

    pgp = sub.add_parser("pg", help="PostgreSQL: what this server offers and how well it is set up")
    pgp.add_argument("action", choices=["status", "optimize", "admin", "admin-set"], help="status/optimize: this server; admin: show which PostgreSQL administrator login Velora uses to create companies; admin-set: choose it")
    pgp.add_argument("--json", action="store_true")
    pgp.add_argument("--user", default="velora_root", help="admin-set: the PostgreSQL administrator (installer default velora_root)")
    pgp.add_argument("--password-file", help="admin-set: file that holds that administrator's password (the installer's is <install folder>/.db-root-password)")

    ops = sub.add_parser("ops", help="workspace health, encrypted backups and retention")
    ops.add_argument("action", choices=["status", "backup", "verify", "prune", "configure", "run-scheduled", "backup-status", "monitor", "recovery-report", "restore-workspace", "rehearse", "dashboard", "alert-configure", "alerts", "metrics", "notify", "serve-dashboard", "postgres-rehearse", "recovery-assurance"])
    ops.add_argument("path", nargs="?", help="backup path for verify, or output path for backup")
    ops.add_argument("--into", help="restore-workspace: the NEW directory to restore into")
    ops.add_argument("--no-files", action="store_true", help="backup: leave the uploaded files/ folder out (back it up separately)")
    ops.add_argument("--keep", type=int, default=14, help="number of newest backups to retain")
    ops.add_argument("--every-hours", type=int, default=24, help="scheduled backup interval (1–720 hours)")
    ops.add_argument("--no-workspace-snapshot", action="store_true", help="schedule database backups only")
    ops.add_argument("--no-verify", action="store_true", help="skip post-backup integrity checks")
    ops.add_argument("--force", action="store_true", help="run scheduled backups even when not due")
    ops.add_argument("--out", help="output file for dashboard or metrics")
    ops.add_argument("--format", choices=["json", "prometheus"], default="prometheus", help="metrics output format")
    ops.add_argument("--email", help="explicit alert recipient (requires SMTP environment configuration)")
    ops.add_argument("--webhook", help="explicit HTTPS webhook destination")
    ops.add_argument("--host", default="127.0.0.1", help="dashboard bind address; loopback is the safe default")
    ops.add_argument("--port", type=int, default=8765, help="dashboard port")
    ops.add_argument("--database-url", help="PostgreSQL URL for isolated restore rehearsal; prefer environment secret")
    sub.add_parser("doctor", help="check this installation and say how to fix problems")
    sub.add_parser("readiness", help="check production workspace configuration and deployment readiness")
    mf = sub.add_parser("manifest", help="create or verify a credential-free deployment integrity manifest")
    mf.add_argument("action", choices=["create", "verify"])
    mf.add_argument("path", nargs="?", help="manifest file path (default: config/deployment-manifest.json)")

    upl = sub.add_parser("upgrade-plan", help="inspect schema and patch changes without modifying databases")
    upl.add_argument("--only", action="append", help="include only this target (control-plane, COMP-001, a site name)")
    upl.add_argument("--out", default="upgrade-plan.json", help="write a reviewable fingerprinted plan file")

    up = sub.add_parser("upgrade", help="upgrade the databases to the installed code (use `velora update` to fetch new code AND upgrade in one step)")
    up.add_argument("--dry-run", action="store_true"); up.add_argument("--partial", action="store_true", help="keep going if one database fails (it stays 'upgrade pending')")
    up.add_argument("--no-backup", action="store_true"); up.add_argument("--only", action="append", help="upgrade just this target (control-plane, COMP-001, a site name)")
    up.add_argument("--force", action="store_true"); up.add_argument("--yes", action="store_true"); up.add_argument("--report-file"); up.add_argument("--plan-file", help="require an unchanged, previously reviewed upgrade-plan.json")

    ud = sub.add_parser("update", help="fetch new code (apps from git, velora from pip) and upgrade; rolls everything back on failure")
    ud.add_argument("--check", action="store_true", help="only list available updates"); ud.add_argument("--dry-run", action="store_true")
    ud.add_argument("--framework-source", help="where to get velora: a pip spec, a wheel file, a directory of wheels or a git URL")
    ud.add_argument("--app", action="append", help="update only this app"); ud.add_argument("--no-apps", action="store_true")
    ud.add_argument("--partial", action="store_true"); ud.add_argument("--no-backup", action="store_true")
    ud.add_argument("--restart-command", help="run after a successful update, e.g. 'sudo systemctl restart velora'"); ud.add_argument("--yes", action="store_true")

    rs = sub.add_parser("restore", help="restore a database from a backup file (atomic)")
    rs.add_argument("file"); rs.add_argument("--company"); rs.add_argument("--control-plane", action="store_true", dest="control_plane")
    rs.add_argument("--no-safety-backup", action="store_true"); rs.add_argument("--yes", action="store_true")

    mt = sub.add_parser("maintenance", help="turn maintenance mode on/off (API answers 503, Desk shows an upgrading screen)")
    mt.add_argument("state", choices=["on", "off", "status"]); mt.add_argument("--message")

    s = sub.add_parser("new-site", help="create a site and its database")
    s.add_argument("name")
    s.add_argument("--db", choices=["sqlite", "postgres"], default=None, help="default: postgres if root/db credentials are given, else sqlite (development)")
    s.add_argument("--db-host", default=os.environ.get("VELORA_DB_HOST", "localhost"))
    s.add_argument("--db-port", type=int, default=int(os.environ.get("VELORA_DB_PORT", 5432)))
    s.add_argument("--db-root-user", default=os.environ.get("VELORA_DB_ROOT_USER", "postgres"))
    s.add_argument("--db-root-password", default=os.environ.get("VELORA_DB_ROOT_PASSWORD"), help="Velora creates a role + database for the site")
    s.add_argument("--db-name", help="existing database (managed hosting)")
    s.add_argument("--db-user", help="existing database user")
    s.add_argument("--db-password", default=os.environ.get("VELORA_DB_PASSWORD"))
    s.add_argument("--developer-mode", action="store_true", help="enable header-based dev sign-in (NEVER in production)")

    d = sub.add_parser("drop-site", help="delete a site (and its database if Velora created it)")
    d.add_argument("name")
    d.add_argument("--db-root-user", default="postgres")
    d.add_argument("--db-root-password", default=os.environ.get("VELORA_DB_ROOT_PASSWORD"))
    d.add_argument("--yes", action="store_true")

    sub.add_parser("list-sites", help="list the sites in this workspace (older one-database-per-site mode)")
    sub.add_parser("use", help="set the default site").add_argument("name")

    a = sub.add_parser("new-app", help="scaffold an app")
    a.add_argument("name")
    a.add_argument("--module")
    a.add_argument("--title")

    t = sub.add_parser("new-doctype", help="scaffold a DocType (JSON + controller + client scripts)")
    t.add_argument("name")
    t.add_argument("--app", required=True)
    t.add_argument("--module")
    t.add_argument("--submittable", action="store_true")
    t.add_argument("--child", action="store_true", help="child table DocType")

    g = sub.add_parser("get-app", help="clone an app from git into the workspace")
    g.add_argument("url")
    g.add_argument("--name")
    g.add_argument("--branch")

    sub.add_parser("list-apps", help="list the apps in this workspace")
    va = sub.add_parser("validate-app", help="validate an app package without executing its code")
    va.add_argument("app")
    ea = sub.add_parser("export-app", help="build a verified, distributable Velora app ZIP")
    ea.add_argument("app")
    ea.add_argument("--output", help="output ZIP path (default: workspace/dist/<app>-<version>.zip)")
    ia = sub.add_parser("import-app-package", help="validate and add a Velora app ZIP to this workspace; does not install it on a site")
    ia.add_argument("package")
    ia.add_argument("--overwrite", action="store_true", help="replace existing app source after validating the archive")
    mp = sub.add_parser("marketplace", help="manage trusted local repositories of validated Velora app packages")
    mp.add_argument("action", choices=["list", "add-source", "remove-source", "import"], help="list sources, add or remove a trusted source, or import a package from one")
    mp.add_argument("name", nargs="?", help="repository name")
    mp.add_argument("value", nargs="?", help="repository directory or package ZIP filename")
    mp.add_argument("--sha256", help="expected package SHA-256 digest")
    mp.add_argument("--overwrite", action="store_true", help="replace existing app source after validation")

    dep = sub.add_parser("deploy", help="promote validated application packages between Velora workspaces")
    dep.add_argument("action", choices=["profile-create", "profile-list", "plan", "promote"], help="create or list deployment profiles, preview a promotion (plan) or carry it out (promote)")
    dep.add_argument("name", nargs="?", help="deployment profile name")
    dep.add_argument("--source", help="source workspace path")
    dep.add_argument("--target", help="target workspace path")
    dep.add_argument("--app", action="append", help="application to promote (repeat for multiple apps)")
    dep.add_argument("--out", help="write deployment plan/report JSON to this path")
    dep.add_argument("--dry-run", action="store_true", help="preview promotion without changing target")
    dep.add_argument("--yes", action="store_true", help="confirm database backups and application installation")

    ia = sub.add_parser("install-app", help="install an app on EVERY company in one step: fetches it (name, git URL or folder), installs its Python packages, restarts")
    ia.add_argument("app", metavar="APP", help="an app name, a built-in app, a git URL or a folder")
    ia.add_argument("--name", help="app name when it cannot be derived from the URL/folder"); ia.add_argument("--branch")
    ia.add_argument("--no-deps", action="store_true", help="do not install Python packages automatically (fail instead)"); ia.add_argument("--no-restart", action="store_true")
    u = sub.add_parser("uninstall-app", help="remove an app from EVERY company in one step (backs up first; data is kept unless --purge)")
    u.add_argument("app")
    u.add_argument("--purge", action="store_true", help="also DELETE the app's data (a backup is always taken first)")
    u.add_argument("--remove-code", action="store_true", help="also delete the app's folder from the workspace")
    u.add_argument("--no-backup", action="store_true"); u.add_argument("--no-restart", action="store_true")
    u.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    m = sub.add_parser("migrate", help="sync a site's database with its installed apps' DocTypes")
    m.add_argument("--dry-run", action="store_true")
    m.add_argument("--all-companies", action="store_true", help="platform mode: migrate every active company database")
    sub.add_parser("doctypes", help="list a site's DocTypes")
    bk = sub.add_parser("backup", help="back up a site's/company's database")
    bk.add_argument("--all", action="store_true", help="back up every database in the workspace")
    # ---- platform (control plane) ----
    pl = sub.add_parser("platform", help="control plane: central identity, tenants, companies")
    pls = pl.add_subparsers(dest="sub", required=True)
    pi = pls.add_parser("init", help="create the control plane (identity + company registry)")
    pi.add_argument("--db", choices=["sqlite", "postgres"], default=None)
    pi.add_argument("--db-host", default=os.environ.get("VELORA_DB_HOST", "localhost"))
    pi.add_argument("--db-port", type=int, default=int(os.environ.get("VELORA_DB_PORT", 5432)))
    pi.add_argument("--db-root-user", default=os.environ.get("VELORA_DB_ROOT_USER", "postgres"))
    pi.add_argument("--db-root-password", default=os.environ.get("VELORA_DB_ROOT_PASSWORD"))
    pi.add_argument("--db-name"); pi.add_argument("--db-user"); pi.add_argument("--db-password", default=os.environ.get("VELORA_DB_PASSWORD"))
    pi.add_argument("--admin-email", required=True)
    pi.add_argument("--admin-password", default=os.environ.get("VELORA_ADMIN_PASSWORD"), help="or set VELORA_ADMIN_PASSWORD, or you will be prompted")
    pls.add_parser("status")
    pls.add_parser("audit", help="recent security events").add_argument("--limit", type=int, default=20)

    tn = sub.add_parser("tenant", help="tenant registry")
    tns = tn.add_subparsers(dest="sub", required=True)
    tns.add_parser("create").add_argument("name")
    tns.add_parser("list")

    co = sub.add_parser("company", help="company registry + database provisioning")
    cos = co.add_subparsers(dest="sub", required=True)
    cc = cos.add_parser("create", help="provision a company database")
    cc.add_argument("name"); cc.add_argument("--tenant", required=True); cc.add_argument("--code")
    cc.add_argument("--apps", default="", help="comma-separated apps to install")
    cc.add_argument("--db", choices=["sqlite", "postgres"], default=None)
    cc.add_argument("--db-host", default=os.environ.get("VELORA_DB_HOST", "localhost"))
    cc.add_argument("--db-port", type=int, default=int(os.environ.get("VELORA_DB_PORT", 5432)))
    cc.add_argument("--db-root-user", default=None, help="PostgreSQL administrator (default: the one the installer set up, see `velora pg admin`)")
    cc.add_argument("--db-root-password", default=os.environ.get("VELORA_DB_ROOT_PASSWORD"))
    cc.add_argument("--db-name"); cc.add_argument("--db-user"); cc.add_argument("--db-password", default=os.environ.get("VELORA_DB_PASSWORD"))
    cos.add_parser("list")
    for n in ("suspend", "activate"):
        cos.add_parser(n).add_argument("company")
    cd = cos.add_parser("drop")
    cd.add_argument("company"); cd.add_argument("--yes", action="store_true")
    cd.add_argument("--db-root-user", default=None); cd.add_argument("--db-root-password", default=os.environ.get("VELORA_DB_ROOT_PASSWORD"))

    us = sub.add_parser("user", help="platform users and company access")
    uss = us.add_subparsers(dest="sub", required=True)
    uc = uss.add_parser("create")
    uc.add_argument("email"); uc.add_argument("--name", default=""); uc.add_argument("--platform-admin", action="store_true")
    uc.add_argument("--password", default=os.environ.get("VELORA_USER_PASSWORD"))
    uss.add_parser("list")
    ug = uss.add_parser("grant", help="let a user into a company with roles")
    ug.add_argument("email"); ug.add_argument("company"); ug.add_argument("--roles", required=True, help="comma-separated, e.g. 'System Manager,Sales User'")
    ur = uss.add_parser("revoke")
    ur.add_argument("email"); ur.add_argument("company")
    up = uss.add_parser("set-password")
    up.add_argument("email"); up.add_argument("--password", default=os.environ.get("VELORA_USER_PASSWORD"))
    for n in ("deactivate", "activate"):
        uss.add_parser(n).add_argument("email")

    for name in ("start", "serve"):
        st = sub.add_parser(name, help="run the server")
        st.add_argument("--host", default="127.0.0.1")
        st.add_argument("--port", type=_port, default=8000)
        st.add_argument("--no-worker", action="store_true", help="do not run the background worker (notifications, reminders, scheduled jobs) inside this server")
        st.add_argument("--auto-upgrade", action=argparse.BooleanOptionalAction, default=None,
                        help="upgrade databases that are behind the installed code when the server starts (default: on after `velora quickstart` / the installer)")
    from .cli_docs import apply_help
    apply_help(p)                                   # every argument has an explanation, in `--help` and in docs/commands.md
    return p


def _cmd_init(args):
    if not args.path.strip():
        raise WorkspaceError("Give the workspace a directory name, e.g. `velora init myworkspace`")
    ws = Workspace.create(args.path)
    print(f"Workspace created at {ws.root}\nNext:\n  cd {args.path}\n  velora new-site erp.local\n  velora new-app myapp\n"
          "  velora --site erp.local install-app myapp\n  velora start")


def _cmd_new_site(args):
    ws = _need_workspace(args)
    db = args.db or ("postgres" if (args.db_root_password or args.db_name) else "sqlite")
    path = provision.create_site(ws, args.name, db=db, db_host=args.db_host, db_port=args.db_port, db_name=args.db_name,
                                 db_user=args.db_user, db_password=args.db_password, root_user=args.db_root_user,
                                 root_password=args.db_root_password, developer_mode=args.developer_mode)
    print(f"Site {args.name} created at {path} ({db})")
    if db == "sqlite":
        print("Using SQLite (development only). For production use PostgreSQL: --db-root-password ... or --db-name/--db-user/--db-password.")
    if args.developer_mode:
        print("WARNING: developer mode trusts X-Velora-User headers. Never enable it on a reachable server.")
    else:
        print("Authentication is not built yet: until it is, the API only works with --developer-mode (local development).")


def _cmd_drop_site(args):
    ws = _need_workspace(args)
    if not args.yes:
        raise WorkspaceError(f"This permanently deletes site {args.name}. Re-run with --yes to confirm.")
    print(f"Site {args.name} dropped: {provision.drop_site(ws, args.name, root_user=args.db_root_user, root_password=args.db_root_password)}")


def _cmd_list_sites(args):
    ws = _need_workspace(args)
    cur = (ws.sites_dir / "currentsite.txt").read_text().strip() if (ws.sites_dir / "currentsite.txt").exists() else ""
    for n in ws.sites():
        cfg = site_mod.read_site_config(ws.site_path(n))
        print(f"{'*' if n == cur else ' '} {n:<32} {cfg.get('db_type', 'sqlite')}")
    if not ws.sites():
        print("No sites yet. Create one with `velora new-site <name>`.")


def _cmd_new_app(args):
    ws = _need_workspace(args)
    root = scaffold.new_app(ws.apps_dir, args.name, args.module, args.title)
    ws.register_app(args.name)
    print(f"App {args.name} created at {root}\nAdd a DocType:  velora new-doctype \"My Thing\" --app {args.name}\n"
          f"Install it:     velora --site <site> install-app {args.name}")


def _cmd_new_doctype(args):
    ws = _need_workspace(args)
    d = scaffold.new_doctype(ws.app_path(args.app), args.app, args.name, args.module, args.submittable, args.child)
    print(f"DocType {args.name} created at {d}\nEdit its JSON, then apply it:  velora --site <site> migrate")


def _cmd_get_app(args):
    ws = _need_workspace(args)
    name = apps_mod.get_app(ws, args.url, args.name, args.branch)
    print(f"App {name} added to the workspace. Install it:  velora --site <site> install-app {name}")


def _cmd_validate_app(args):
    from .app_package import inspect_app
    ws = _need_workspace(args)
    report = inspect_app(ws, args.app)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


def _cmd_marketplace(args):
    from . import marketplace
    ws = _need_workspace(args)
    if args.action == "list":
        print(json.dumps(marketplace.list_packages(ws), indent=2))
    elif args.action == "add-source":
        if not args.name or not args.value:
            raise WorkspaceError("Use: velora marketplace add-source NAME DIRECTORY")
        print(json.dumps(marketplace.add_source(ws, args.name, args.value), indent=2))
    elif args.action == "remove-source":
        if not args.name:
            raise WorkspaceError("Use: velora marketplace remove-source NAME")
        marketplace.remove_source(ws, args.name)
        print(f"Removed marketplace repository {args.name}.")
    elif args.action == "import":
        if not args.name or not args.value:
            raise WorkspaceError("Use: velora marketplace import REPOSITORY PACKAGE.zip")
        result = marketplace.import_package(ws, args.name, args.value, expected_sha256=args.sha256, overwrite=args.overwrite)
        print(json.dumps(result, indent=2))
    return 0


def _cmd_deploy(args):
    from . import deployment
    ws = _need_workspace(args)
    if args.action == "profile-create":
        if not args.name or not args.source or not args.target or not args.app:
            raise WorkspaceError("Use: velora deploy profile-create NAME --source PATH --target PATH --app APP [--app APP]")
        result = deployment.create_profile(ws, args.name, args.source, args.target, args.app)
    elif args.action == "profile-list":
        result = deployment.list_profiles(ws)
    elif args.action == "plan":
        if not args.name:
            raise WorkspaceError("Use: velora deploy plan PROFILE")
        result = deployment.build_plan(ws, args.name)
    else:
        if not args.name:
            raise WorkspaceError("Use: velora deploy promote PROFILE [--dry-run | --yes]")
        if not args.dry_run and not args.yes:
            raise WorkspaceError("Promotion changes target application code and company databases. Review `velora deploy plan PROFILE`, then repeat with --yes.")
        result = deployment.promote(ws, args.name, dry_run=args.dry_run, log=print)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))
    return 0 if not isinstance(result, dict) or result.get("status") not in ("rolled_back", "failed") else 2


def _cmd_export_app(args):
    from .app_package import build_app_archive
    ws = _need_workspace(args)
    data, report = build_app_archive(ws, args.app)
    output = Path(args.output).expanduser() if args.output else ws.root / "dist" / f"{args.app}-{report['version']}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print(f"App {args.app} {report['version']} packaged: {output} ({len(data)} bytes)")
    print("The archive is not installed on any site. Use import-app-package in the destination workspace, then install-app for the intended site.")


def _cmd_import_app_package(args):
    from .app_package import install_package
    ws = _need_workspace(args)
    name = install_package(ws, Path(args.package).expanduser().read_bytes(), overwrite=args.overwrite)
    print(f"App {name} added to workspace. It is not installed on any site. Validate it, then run velora --site <site> install-app {name}.")


def _cmd_list_apps(args):
    ws = _need_workspace(args)
    installed = []
    try:
        site = _site(args, ws)
        with site_mod.use(site):
            installed = site.installed_apps()
        where = site.name
    except WorkspaceError:
        where = None
    for a in ws.apps():
        mark = ("installed" if a in installed else "-") if where else ""
        print(f"{a:<24} {apps_mod.app_version(a):<10} {mark}")
    if not ws.apps():
        print("No apps yet. Create one with `velora new-app <name>`.")
    if where:
        print(f"(installed status is for site {where})")


def _only(args) -> list[str] | None:
    """The global --company / --site flags restrict a command to one target; without them it applies to every company."""
    return [args.company] if getattr(args, "company", None) else ([args.site] if getattr(args, "site", None) else None)


def _cmd_install_app(args):
    from . import lifecycle
    ws = _need_workspace(args)
    rep = lifecycle.install_everywhere(ws, args.app, only=_only(args), name=args.name, branch=args.branch, with_packages=not args.no_deps, do_restart=not args.no_restart, log=print)
    failed = [r for r in rep["results"] if r["status"] == "failed"]
    ok = [r for r in rep["results"] if r["status"] == "installed"]
    print(f"\n{rep['app']}: installed on {len(ok)} of {len(rep['results'])} company(ies)" + (f", {len(failed)} FAILED (the others are fine; fix and run the same command again)" if failed else "."))
    for r in failed:
        print(f"Error: {r['label']}: {r['error']}", file=sys.stderr)                 # scripts read errors from stderr
    return 1 if failed else 0


def _cmd_uninstall_app(args):
    from . import lifecycle
    ws = _need_workspace(args)
    if not args.yes:
        if not sys.stdin.isatty():
            raise WorkspaceError(f"This removes {args.app} from the companies. Re-run with --yes to confirm.")
        what = "and DELETE ITS DATA" if args.purge else "(its data is kept)"
        if input(f"Remove {args.app} from {'the selected company' if _only(args) else 'EVERY company'} {what}? A backup is taken first. [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 0
    rep = lifecycle.uninstall_everywhere(ws, args.app, only=_only(args), purge=args.purge, backup=not args.no_backup, remove_code=args.remove_code, do_restart=not args.no_restart, log=print)
    failed = [r for r in rep["results"] if r["status"] == "failed"]
    print(f"\n{args.app} removed from {len(rep['results']) - len(failed)} company(ies)." + (f" {len(failed)} FAILED." if failed else ""))
    for r in failed:
        print(f"Error: {r['label']}: {r['error']}", file=sys.stderr)
    return 1 if failed else 0


def _site_context(args):
    """(workspace|None, site) - falls back to env-configured single-site mode outside a workspace."""
    ws = Workspace.discover(args.workspace)
    if ws is not None:
        ws.activate()
        return ws, _site(args, ws)
    if args.site or args.company or not os.environ.get("VELORA_DB_URL"):
        # never guess: silently creating ./velora_dev.db or ignoring --site would hide a mistake
        raise WorkspaceError("Not inside a Velora workspace. Run `velora init <dir>` (or cd into one, or set VELORA_WORKSPACE).")
    from . import runtime
    runtime.init()
    return None, site_mod.current()


def _cmd_migrate(args):
    from .db import schema
    if args.all_companies:
        ws = _need_workspace(args)
        plane = _plane(args, ws)
        failed = 0
        for r in plane.migrate_all(dry_run=args.dry_run):
            if "error" in r:
                failed += 1
                print(f"{r['company']}: FAILED - {r['error']}")
            elif "skipped" in r:
                print(f"{r['company']}: skipped ({r['skipped']})")
            else:
                print(f"{r['company']}: " + (f"{len(r['plan'])} change(s)" if r["plan"] else "up to date"))
        if failed:
            raise WorkspaceError(f"{failed} company database(s) failed to migrate (the others were migrated)")
        return
    ws, site = _site_context(args)
    with site_mod.use(site):
        if args.dry_run or ws is None:
            if not args.dry_run:
                schema.ensure_system_tables()
            site.load()                                      # always diff against the DocType JSON as it is on disk now
            plan = schema.migrate(dry_run=args.dry_run)
        else:                                                # schema + data patches + version stamp, like `bench migrate`
            from .upgrade import engine
            tgt = _target_for(args, ws)
            res = engine.upgrade_target(tgt, print)
            plan = res["schema"] + res.get("warnings", [])
    print("\n".join(plan) if plan else "Nothing to migrate.")
    if args.dry_run and plan:
        print("(dry run - nothing applied)")


def _cmd_doctypes(args):
    _, site = _site_context(args)
    with site_mod.use(site):
        for d in sorted(site.registry.all(), key=lambda d: (d.app, d.name)):
            kind = "child" if d.istable else ("submittable" if d.is_submittable else "")
            print(f"{d.app:<16} {d.name:<28} {len(d.fields):>3} fields  {kind}")


def _cmd_backup(args):
    ws = _need_workspace(args)
    if getattr(args, "all", False):
        from .upgrade import engine
        for t in engine.collect_targets(ws):
            print(f"{t.label}: {provision_backup(t, ws)}")
        return
    if args.company:
        plane = _plane(args, ws)
        co = plane.registry.get_company(args.company)
        if co is None:
            raise WorkspaceError(f"No such company: {args.company}")
        print(f"Backup written to {plane.backup_company(co)}")
        return
    name = ws.current_site(args.site)
    print(f"Backup written to {provision.backup_site(ws, name)}")


def _cmd_platform(args):
    from .controlplane import ControlPlane, models as cpm
    from sqlalchemy import select
    ws = _need_workspace(args)
    if args.sub == "init":
        db = args.db or ("postgres" if (args.db_root_password or args.db_name) else "sqlite")
        plane = ControlPlane.create(ws, db=db, db_host=args.db_host, db_port=args.db_port, db_name=args.db_name, db_user=args.db_user,
                                    db_password=args.db_password, root_user=args.db_root_user, root_password=args.db_root_password,
                                    admin_email=args.admin_email, admin_password=_password(args.admin_password, "Admin password"))
        print(f"Control plane created ({db}). Platform admin: {args.admin_email}")
        if os.environ.get("VELORA_MASTER_KEY"):
            print("Master key taken from VELORA_MASTER_KEY: keep it safe - without it company credentials cannot be decrypted.")
        else:
            print(f"Master key written to {plane.platform_dir / 'master.key'} - BACK IT UP SEPARATELY from the database; without it company credentials cannot be decrypted.")
        if db == "sqlite":
            print("Using SQLite (development only).")
        print("Next:  velora tenant create \"My Group\"  ->  velora company create \"My Company\" --tenant TEN-001  ->  velora user grant ...")
        return
    plane = _plane(args, ws)
    if args.sub == "status":
        cos = plane.registry.list_companies()
        print(f"Control plane: {plane.cfg['db_type']} | tenants: {len(plane.registry.list_tenants())} | companies: {len(cos)} "
              f"({sum(1 for c in cos if c['status'] == 'active')} active) | users: {len(plane.identity.list_users())}")
    elif args.sub == "audit":
        with plane.engine.connect() as c:
            for r in c.execute(select(cpm.audit).order_by(cpm.audit.c.ts.desc()).limit(args.limit)).mappings():
                print(f"{r['ts']:%Y-%m-%d %H:%M:%S}  {r['event']:<24} {r['actor'] or '-':<26} {r['subject'] or ''}")


def _cmd_tenant(args):
    plane = _plane(args, _need_workspace(args))
    if args.sub == "create":
        t = plane.registry.create_tenant(args.name)
        print(f"Tenant {t['id']} created: {t['name']}")
    else:
        for t in plane.registry.list_tenants():
            print(f"{t['id']:<10} {t['name']:<40} {t['status']}")


def _cmd_company(args):
    ws = _need_workspace(args)
    plane = _plane(args, ws)
    if args.sub == "create":
        db = args.db or ("postgres" if (args.db_root_password or args.db_name) else "sqlite")
        row = plane.provisioning.provision_company(
            args.tenant, args.name, code=args.code, apps=[a for a in args.apps.split(",") if a.strip()], db=db, db_host=args.db_host,
            db_port=args.db_port, db_name=args.db_name, db_user=args.db_user, db_password=args.db_password,
            root_user=args.db_root_user, root_password=args.db_root_password)
        print(f"Company {row['id']} ({row['name']}) is {row['status']} - database {row['db_engine']}:{row['db_name']}")
        print(f"Give someone access:  velora user grant <email> {row['id']} --roles 'System Manager'")
    elif args.sub == "list":
        from . import __version__
        for c in plane.registry.list_companies():
            drift = "" if c["schema_version"] == __version__ or c["status"] != "active" else f"  (schema {c['schema_version']} - run `velora migrate --all-companies`)"
            print(f"{c['id']:<10} {c['name']:<32} {c['tenant_name']:<24} {c['db_engine']:<9} {c['status']}{drift}")
            if c.get("provisioning_error") and c["status"] != "active":
                print(f"{'':<10} why: {str(c['provisioning_error'])[:200]}  (remove it with `velora company drop {c['id']}`)")
        if not plane.registry.list_companies():
            print("No companies yet.")
    elif args.sub in ("suspend", "activate"):
        co = plane.registry.get_company(args.company)
        if co is None:
            raise WorkspaceError(f"No such company: {args.company}")
        plane.registry.set_status(co["id"], "suspended" if args.sub == "suspend" else "active")
        print(f"Company {co['id']} is now {'suspended' if args.sub == 'suspend' else 'active'}")
    elif args.sub == "drop":
        co = plane.registry.get_company(args.company)
        if co is None:
            raise WorkspaceError(f"No such company: {args.company}")
        if not args.yes:
            raise WorkspaceError(f"This permanently removes company {co['id']} ({co['name']}) and, if Velora created it, its database. Re-run with --yes.")
        print(f"Company {co['id']} dropped: {plane.provisioning.drop_company(co['id'], root_user=args.db_root_user, root_password=args.db_root_password)}")


def _cmd_user(args):
    plane = _plane(args, _need_workspace(args))
    idn = plane.identity
    if args.sub == "create":
        u = idn.create_user(args.email, args.name, _password(args.password), is_platform_admin=args.platform_admin)
        print(f"User {u['email']} created")
    elif args.sub == "list":
        for u in idn.list_users():
            flags = ("admin " if u["is_platform_admin"] else "") + ("" if u["is_active"] else "INACTIVE")
            print(f"{u['email']:<36} {u['full_name'] or '':<26} {flags}")
    elif args.sub == "grant":
        co = plane.registry.get_company(args.company)
        if co is None:
            raise WorkspaceError(f"No such company: {args.company}")
        idn.grant(args.email, co["id"], args.roles.split(","))
        print(f"{args.email} can now work in {co['id']} as: {', '.join(sorted(r.strip() for r in args.roles.split(',') if r.strip()))}")
    elif args.sub == "revoke":
        co = plane.registry.get_company(args.company)
        idn.revoke(args.email, co["id"] if co else args.company)
        print(f"{args.email} no longer has access to {args.company}")
    elif args.sub == "set-password":
        idn.set_password(args.email, _password(args.password))
        print("Password updated; all sessions for this user were signed out")
    else:
        idn.set_active(args.email, args.sub == "activate")
        print(f"{args.email} {'activated' if args.sub == 'activate' else 'deactivated (sessions revoked)'}")


def _print_upgrade(rep: dict) -> None:
    icon = {"upgraded": "done", "up_to_date": "current", "pending": "pending", "failed": "FAILED", "failed (restored)": "FAILED (restored)", "rolled_back": "restored"}
    for t in rep["targets"]:
        extra = ""
        if t.get("patches_run"):
            extra += f", patches: {len(t['patches_run'])}"
        elif t.get("patches"):
            extra += f", patches: {len(t['patches'])} pending"
        if t.get("schema_changes"):
            extra += f", schema changes: {t['schema_changes']}"
        print(f"  {t['label']:<34} {icon.get(t['status'], t['status']):<18}{extra}" + (f"\n      -> {t['error']}" if t.get("error") else ""))
        for w in t.get("warnings", []):
            print(f"      ! {w}")
    status = rep["status"]
    msg = {"success": "Upgrade complete.", "up_to_date": "Everything is already up to date.", "dry_run": "Dry run: nothing was changed.",
           "partial": "Upgrade finished PARTIALLY: failed databases stay in 'upgrade pending' (they answer 503).",
           "rolled_back": "UPGRADE FAILED - every database was restored to its state before the upgrade.",
           "failed": "UPGRADE FAILED and no backup was taken, so the databases could NOT be restored automatically."}.get(status, status)
    print(msg)
    if status in ("success", "rolled_back", "partial"):
        print("The welcome page in the Desk (book icon) explains, step by step, what just happened.")
    if rep.get("snapshot"):
        print(f"Backups: {rep['snapshot']}")
    for r in (rep.get("rollback") or []) if isinstance(rep.get("rollback"), list) else []:
        if not r["restored"]:
            print(f"  COULD NOT RESTORE {r['id']}: {r.get('error')}\n  restore it by hand: {r.get('manual')}")
    if isinstance(rep.get("rollback"), str):
        print(rep["rollback"])


def _cmd_upgrade_plan(args):
    from .upgrade.plan import build_plan
    ws = _need_workspace(args)
    plan = build_plan(ws, only=args.only)
    out = Path(args.out)
    out.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
    print(f"Upgrade plan written to {out.resolve()}")
    print(f"Fingerprint: {plan['fingerprint']}")
    for target in plan["targets"]:
        print(f"  {target['label']}: {len(target['schema'])} schema change(s), {len(target['patches'])} pending patch(es), {len(target['warnings'])} warning(s)")
    print("No database was changed. Review the file, then execute with: velora upgrade --plan-file " + str(out))
    return 0


def _cmd_upgrade(args):
    from .upgrade.engine import UpgradeEngine
    from . import layout
    ws = _need_workspace(args)
    if args.plan_file:
        from .upgrade.plan import verify_plan_file
        if args.no_backup:
            raise WorkspaceError("A reviewed --plan-file requires backups; remove --no-backup.")
        verified = verify_plan_file(ws, args.plan_file, only=args.only)
        print(f"Reviewed plan verified: {verified['fingerprint']}")
    if not args.dry_run:
        layout.tidy(ws)
    rep = UpgradeEngine(ws, partial=args.partial, backup=not args.no_backup, only=args.only, force=args.force).run(dry_run=args.dry_run)
    if args.report_file:
        Path(args.report_file).write_text(json.dumps(rep, indent=2, default=str))
    _print_upgrade(rep)
    if rep["status"] not in ("dry_run", "up_to_date"):
        from . import eventlog
        title, ok, steps, _ = eventlog.from_update_report({"status": rep["status"], "upgrade": rep})
        eventlog.record(ws, "upgrade", title.replace("Update", "Upgrade"), steps, ok=ok)
    return 0 if rep["status"] in ("success", "up_to_date", "dry_run") else 3


def _cmd_update(args):
    from .upgrade import update as upd
    ws = _need_workspace(args)
    if args.check:
        res = upd.check_updates(ws, args.framework_source or ws.common_config().get("update", {}).get("framework_source"))
        fw = res["framework"]
        print(f"velora {fw['current']}  " + (f"-> {fw['latest']} available" if fw["latest"] else ("(up to date)" if fw["source"] != "(none configured)" else "(no update source configured: use --framework-source)")))
        for a in res["apps"]:
            state = f"{a['behind']} new commit(s)" + (f" (version {a['latest']})" if a["latest"] else "") if a["behind"] else (a["note"] or "up to date")
            print(f"{a['name']:<24} {a['version']:<10} {state}" + ("  [local changes]" if a["dirty"] else ""))
        pending = bool(fw["latest"]) or any(a["behind"] for a in res["apps"])
        return 10 if pending else 0
    rep = upd.update(ws, framework_source=args.framework_source, apps=args.app, do_apps=not args.no_apps, partial=args.partial, backup=not args.no_backup,
                     restart_command=args.restart_command, dry_run=args.dry_run, log=print)
    if args.framework_source and rep["status"] in ("success", "up_to_date"):         # tell it once: it remembers where updates come from
        ws.update_config(update={**ws.common_config().get("update", {}), "framework_source": args.framework_source})
    if rep["status"] == "dry_run":
        fw = rep["code"]["framework"]
        print(f"Would update velora {fw['from']} -> {fw['to']}" if fw["to"] else "No framework update.")
        for a in rep["code"]["apps"]:
            print(f"Would update {a['name']} ({a['behind']} commit(s) -> {a['to'] or '?'})")
        print("Data that needs upgrading right now:")
        _print_upgrade(rep["upgrade"])
        return 0
    if rep["status"] == "rolled_back" and rep.get("error"):
        print(f"\nUPDATE FAILED: {rep['error']}\nThe code and the databases were rolled back to how they were before the update.")
        for a in rep.get("code_rollback", {}).get("apps", []):
            print(f"  app {a['name']}: {'restored to ' + a['sha'] if a['restored'] else 'NOT restored'}")
        fw = rep.get("code_rollback", {}).get("framework")
        if fw:
            print(f"  velora: {'restored to ' + fw['version'] if fw['restored'] else 'NOT restored - run: ' + fw['manual']}")
        return 3                                           # the data upgrade's own summary was already streamed above
    r = rep.get("restart")
    if r:
        print("Restarted." if r["ok"] else f"Restart: {r['output']}")
    return 0 if rep["status"] in ("success", "up_to_date") else 3


def _target_for(args, ws):
    from .upgrade import engine
    if args.company:
        pool = engine.collect_targets(ws, [args.company])
    elif getattr(args, "control_plane", False):
        pool = engine.collect_targets(ws, ["control-plane"])
    else:
        pool = engine.collect_targets(ws, [ws.current_site(args.site)])
    return pool[0]


def _cmd_restore(args):
    from .upgrade import engine, maintenance
    ws = _need_workspace(args)
    t = _target_for(args, ws)
    f = Path(args.file)
    if not f.is_file():
        raise WorkspaceError(f"No such backup file: {f}")
    if not args.yes:
        raise WorkspaceError(f"This REPLACES the current contents of {t.label} with {f.name}. Re-run with --yes to confirm.")
    owns = maintenance.status(ws) is None
    if owns:
        maintenance.enable(ws, "Restoring a backup. This page will reload by itself when it is ready.", owner="restore")
    try:
        if not args.no_safety_backup:
            safety = provision_backup(t, ws, "safety", f"pre-restore-{t.id}")
            print(f"Safety backup of the current state: {safety}")
        engine.restore_target(t, f)
        print(f"{t.label} restored from {f.name}.")
    finally:
        if owns:
            maintenance.disable(ws)


def provision_backup(t, ws, folder: str = "manual", label: str | None = None) -> Path:
    return provision.backup_database(dict(t.cfg), t.sqlite_file, ws.root / "backups" / folder, label or t.id)


def _cmd_maintenance(args):
    from .upgrade import maintenance
    ws = _need_workspace(args)
    if args.state == "on":
        maintenance.enable(ws, args.message or maintenance.DEFAULT_MESSAGE, owner="manual")
        print("Maintenance mode is ON: the API answers 503 until you run `velora maintenance off`.")
    elif args.state == "off":
        maintenance.disable(ws)
        print("Maintenance mode is OFF.")
    else:
        st = maintenance.status(ws)
        print(f"ON since {st['since']} ({st.get('owner', '?')}): {st['message']}" if st else "OFF")


def _cmd_new_doctypes(args):
    from .devtools import creator
    from .exceptions import MetaError
    ws, site = _site_context(args)
    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise WorkspaceError(f"{args.file} is not valid JSON: {e}") from None
    flags = {k: True for k, on in (("is_child", args.child), ("is_submittable", args.submittable), ("track_changes", args.track_changes)) if on}
    if args.autoname_field:
        flags.update(is_autoname=True, autoname_field_name=args.autoname_field)
    with site_mod.use(site):
        site.load()
        p = creator.plan(data, app=args.app, module=args.module, name=args.name, flags=flags, on_conflict=args.on_conflict)
        rep = p.report()
        for w in rep["warnings"]:
            print(f"warning: {w}")
        for e in rep["errors"]:
            print(f"error: {e}", file=sys.stderr)
        if rep["errors"]:
            print("Nothing was created.", file=sys.stderr)
            return 1
        for d in rep["doctypes"]:
            print(f"{'Would create' if args.dry_run else 'Creating'} {d['name']} ({d['fields']} fields{', child table' if d['child'] else ''}) at {d['path']}")
        for n in rep["skipped"]:
            print(f"Skipped {n} (already exists)")
        if args.dry_run:
            return 0
        try:
            out = creator.create(p)
        except MetaError as e:
            raise WorkspaceError(str(e)) from None
    print(f"Created {len(out['created'])} DocType(s). Apply them to your database(s) with `velora migrate` (all companies: `velora upgrade`).")


def _cmd_deps(args):
    from . import optional
    if args.action == "list":
        for name, e in optional.EXTRAS.items():
            st = optional.status(name)
            mark = "ready  " if st["complete"] else f"{st['installed']}/{st['total']}    "
            print(f"{name:<10} {mark} {e.description}")
        print('\nInstall with:  velora deps install <extra...>   or   pip install "velora[<extra>]"')
        return
    if args.action == "check":
        bad = 0
        ws = Workspace.discover(args.workspace)
        for app in (ws.apps() if ws else []):
            ws.activate()
            try:
                reqs = getattr(__import__(f"{app}.hooks", fromlist=["x"]), "required_packages", [])
            except Exception:  # noqa: BLE001
                continue
            for p in optional.check_packages(reqs):
                print(f"{app}: {p}")
                bad += 1
        print("All packages the installed apps declare are ready." if not bad else f"{bad} problem(s). Fix with `velora deps install --app <app>`.")
        return 1 if bad else 0
    if args.app:
        ws = _need_workspace(args)
        ws.activate()
        reqs = list(getattr(__import__(f"{args.app}.hooks", fromlist=["x"]), "required_packages", []))
        if not reqs:
            print(f"{args.app} declares no required packages.")
            return
    else:
        if not args.extras:
            raise WorkspaceError("Name what to install, e.g. `velora deps install pdf data`, or `--app <app>`. See `velora deps list`.")
        try:
            reqs = optional.requirements_for(args.extras)
        except optional.DependencyError as e:
            raise WorkspaceError(str(e)) from None
    def remember():                                                   # `velora update` keeps the extras you chose current
        if args.extras and not args.app:
            try:
                w = Workspace.discover(args.workspace)
                if w is not None:
                    w.update_config(extras=sorted({*w.common_config().get("extras", []), *[e for e in args.extras if e in optional.EXTRAS]}))
            except OSError:
                pass
    todo = [r for r in reqs if args.upgrade or not optional.check_requirement(r)["ok"]]
    if not todo:
        print("Everything requested is already installed.")
        remember()
        return
    print("Will install:\n  " + "\n  ".join(todo))
    if args.dry_run:
        return
    if not args.yes and sys.stdin.isatty() and input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Cancelled.")
        return
    try:
        out = optional.install(todo, upgrade=args.upgrade)
    except optional.DependencyError as e:
        raise WorkspaceError(str(e)) from None
    print("Installed." + (f"\n{out['output']}" if out["output"] else ""))
    remember()


def _cmd_apply_update(args):
    """On the NEW code: packages, then the data upgrade (backup + rollback), then the built-in features. One report."""
    from . import lifecycle
    from .upgrade.engine import UpgradeEngine
    ws = _need_workspace(args)
    packages = lifecycle.ensure_all_packages(ws, log=print)
    rep = UpgradeEngine(ws, partial=args.partial, backup=not args.no_backup).run()
    features = []
    if rep["status"] in ("success", "up_to_date"):
        features = lifecycle.ensure_default_apps(ws, ws.common_config().get("default_apps", []), log=print)
    rep["packages"], rep["features"] = packages, features
    if args.report_file:
        Path(args.report_file).write_text(json.dumps(rep, indent=2, default=str))
    _print_upgrade(rep)
    return 0 if rep["status"] in ("success", "up_to_date") else 3


def _data_context(args):
    from .permissions import ADMINISTRATOR, session_as
    ws, site = _site_context(args)
    return site, site_mod.use(site), session_as(ADMINISTRATOR)


def _cmd_import_data(args):
    from . import dataimport as di
    f = Path(args.file)
    if not f.is_file():
        raise WorkspaceError(f"No such file: {args.file}")
    site, c1, c2 = _data_context(args)
    with c1, c2:
        site.load()
        opts = di.Options(mode=args.mode, submit=args.submit, dry_run=args.dry_run, atomic=args.atomic, keep_names=args.keep_names, date_format=args.date_format, match=args.match, max_rows=args.max_rows)
        try:
            rep = di.import_file(args.doctype, f.read_bytes(), f.name, opts)
        except di.ValidationError as e:
            raise WorkspaceError(str(e)) from None
    r = rep.to_dict()
    verb = "Would create" if args.dry_run else "Created"
    print(f"{'DRY RUN (nothing was saved): ' if args.dry_run else ''}{r['total']} document(s) in the file. {verb} {r['created']}, {'would update' if args.dry_run else 'updated'} {r['updated']}, failed {r['failed']}.")
    if r["rolled_back"] and not args.dry_run:
        print("All or nothing: because some failed, NOTHING was imported.")
    if r["unknown_columns"]:
        print(f"Ignored columns (they match no importable field; calculated fields are never imported): {', '.join(r['unknown_columns'])}")
    for e in r["errors"][:20]:
        print(f"  line {e['row']}{' ' + e['field'] if e['field'] else ''}: {e['message']}")
    if len(r["errors"]) > 20:
        print(f"  ... and {len(r['errors']) - 20} more (use --report FILE for all of them)")
    if args.report and r["failed_rows"]:
        Path(args.report).write_text(di.errors_csv(r), encoding="utf-8-sig")
        print(f"The failed rows, with the reason, are in {args.report}: fix them and import that file.")
    return 1 if r["failed"] else 0


def _cmd_export_data(args):
    from . import dataimport as di
    flt = None
    if args.filters:
        try:
            flt = json.loads(args.filters)
        except ValueError:
            raise WorkspaceError("--filters must be JSON, like '[[\"status\",\"=\",\"Active\"]]'") from None
    site, c1, c2 = _data_context(args)
    with c1, c2:
        site.load()
        data, name, _ct, n = di.export_data(args.doctype, args.format, flt, args.limit)
    out = Path(args.out or name)
    out.write_bytes(data)
    print(f"Exported {n} {args.doctype} document(s) to {out}. Import them elsewhere with:  velora import-data \"{args.doctype}\" {out} --keep-names" if args.format == "json" else f"Exported {n} {args.doctype} document(s) to {out}.")


def _cmd_import_template(args):
    from . import dataimport as di
    site, c1, c2 = _data_context(args)
    with c1, c2:
        site.load()
        data, name, _ct = di.template(args.doctype, args.format)
    out = Path(args.out or name)
    out.write_bytes(data)
    print(f"Wrote {out}. Fill it in, then:  velora import-data \"{args.doctype}\" {out} --dry-run")


def _cmd_domain(args):
    from . import domains
    ws = _need_workspace(args)
    if args.action == "list":
        rows = domains.listing(ws)
        if not rows:
            print("No domains yet. Add one:  velora domain add erp.acme.com COMP-001")
            return
        for r in rows:
            print(f"{r['domain']:<34} {r['company_id']:<10} {r['company_name']:<26} {'primary ' if r['is_primary'] else '        '}{'https ' if r['tls'] else 'http  '}{'locked' if r['locked'] else 'shared'}")
        return
    if not args.name:
        raise WorkspaceError(f"Give the address, e.g.  velora domain {args.action} erp.acme.com")
    if args.action == "check":
        from .controlplane.registry import normalize_domain
        from .exceptions import ValidationError
        try:
            d = normalize_domain(args.name)
        except ValidationError as e:
            raise WorkspaceError(str(e)) from None
        ips = domains.resolve(d)
        print(f"{d}: " + (f"points to {', '.join(ips)}" if ips else "does not resolve in DNS yet (create an A record to this server)"))
        return
    if args.action == "remove":
        domains.remove(ws, args.name)
        return
    domains.add(ws, args.name, args.target or getattr(args, "company", None), primary=args.primary, locked=not args.unlocked, tls=False if args.no_tls else None, dry_run=args.dry_run)


def _cmd_worker(args):
    import signal

    from . import worker
    ws = _need_workspace(args)
    ws.activate()
    if args.once:
        res = worker.run_once(ws, log=print)
        n = sum(sum(1 for x in r["results"] if x.get("freq") != "jobs") for r in res)
        print(f"Ran {n} task(s) across {len(res)} database(s).")
        return 1 if any(not x["ok"] for r in res for x in r["results"]) else 0
    stop = {"now": False}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.update(now=True))
    worker.serve(ws, interval=args.interval, log=print, should_stop=lambda: stop["now"])
    print("Worker stopped.")


def _cmd_pg(args):
    import json as _json

    from . import pg as pgmod
    if args.action in ("admin", "admin-set"):
        from . import pgadmin
        ws = Workspace.discover(args.workspace)
        if ws is None:
            raise WorkspaceError("Not inside a Velora workspace (cd into one, or set VELORA_WORKSPACE).")
        if args.action == "admin-set":
            if not args.password_file:
                raise WorkspaceError("give --password-file, the file that holds the administrator's password")
            try:
                pgadmin.save(ws, args.user, args.password_file)
            except ValueError as exc:
                raise WorkspaceError(str(exc)) from None
        st = pgadmin.status(ws)
        print(_json.dumps(st) if args.json else (f"PostgreSQL administrator: {st['user']} (login found: {'yes, from ' + st['source'] if st['configured'] else 'NO - run `velora pg admin-set --password-file FILE`'})"))
        return 0 if st["configured"] else 1
    ws, site = _site_context(args)
    with site_mod.use(site), site.engine.connect() as conn:
        site.load()
        if args.action == "optimize":
            out = pgmod.optimize(conn)
            conn.commit()
            print(_json.dumps(out) if args.json else ("Not PostgreSQL: nothing to optimise." if not out["postgresql"] else
                  "Extensions: " + ", ".join(f"{k} {'ready' if v else 'NOT allowed for this role (ask your database administrator)'}" for k, v in out["extensions"].items()) + "\nStatistics refreshed (ANALYZE)."))
            return
        st = pgmod.status(conn)
    if args.json:
        print(_json.dumps(st, default=str, indent=2))
        return
    if not st["postgresql"]:
        print("\n".join(st["advice"]))
        return
    print(f"PostgreSQL {st['version']}")
    print("Extensions installed: " + ", ".join(st["extensions"]["installed"]))
    o = st["objects"]
    print(f"Database rules applied: {len(o['applied'])} ({', '.join(o['applied']) or 'none'})" + (f"; PENDING: {', '.join(o['pending'])}" if o["pending"] else ""))
    for t in st["largest_tables"][:5]:
        print(f"  {t['table']:<34} {t['size']:>10}  " + (f"~{t['rows_estimate']:,} rows" if t["rows_estimate"] is not None else "rows not counted yet (run `velora pg optimize`)"))
    print("\n" + ("Advice:\n  - " + "\n  - ".join(st["advice"]) if st["advice"] else "No advice: this server is set up well."))


def _backup_password(label: str = "Backup encryption password") -> str:
    return _password(os.environ.get("VELORA_BACKUP_PASSWORD"), label)


def _cmd_ops(args):
    from . import operations
    if args.action == "restore-workspace":                    # needs NO workspace: after a disaster there is only the backup file and a new machine
        if not args.path:
            raise WorkspaceError("Provide the backup file to restore")
        if not args.into:
            raise WorkspaceError("Provide --into DIRECTORY: a new, empty directory to restore into")
        report = operations.restore_encrypted_backup(args.path, _backup_password(), args.into)
        print(json.dumps(report, indent=2))
        return 0
    if args.action == "verify":                               # likewise: check a backup on any machine
        if not args.path:
            raise WorkspaceError("Provide the backup file path to verify")
        print(json.dumps(operations.verify_encrypted_backup(args.path, _backup_password()), indent=2))
        return 0
    ws = _need_workspace(args)
    if args.action == "dashboard":
        from .ops_console import write_dashboard
        path = write_dashboard(ws, args.out)
        print(f"Operations dashboard generated: {path}")
        return 0
    if args.action == "serve-dashboard":
        import uvicorn
        from .live_dashboard import create_dashboard_app
        if not (1 <= args.port <= 65535): raise WorkspaceError("Dashboard port must be between 1 and 65535")
        app = create_dashboard_app(ws)
        uvicorn.run(app, host=args.host, port=args.port, access_log=False)
        return 0
    if args.action == "postgres-rehearse":
        if not args.path: raise WorkspaceError("Provide a PostgreSQL custom/tar dump file")
        from .recovery_assurance import rehearse_postgres_restore, record_rehearsal, RecoveryRehearsalError
        try:
            report = rehearse_postgres_restore(args.path, database_url=args.database_url)
            record_rehearsal(ws.root, report)
        except RecoveryRehearsalError as exc:
            if exc.result:
                record_rehearsal(ws.root, exc.result)            # a FAILED rehearsal is evidence too: without it the log could only ever say "passed"
            print(str(exc)); return 1
        print(json.dumps(report, indent=2)); return 0
    if args.action == "recovery-assurance":
        from .recovery_assurance import recovery_assurance_report
        print(json.dumps(recovery_assurance_report(ws.root), indent=2)); return 0
    if args.action == "alert-configure":
        from .ops_console import configure_alert_policy
        print(json.dumps(configure_alert_policy(ws), indent=2))
        return 0
    if args.action == "alerts":
        from .ops_console import evaluate_alerts
        report = evaluate_alerts(ws)
        print(json.dumps(report, indent=2))
        return 1 if any(a.get("severity") == "critical" for a in report.get("alerts", [])) else 0
    if args.action == "notify":
        from .ops_console import evaluate_alerts
        from .notification_delivery import deliver_alerts
        report = evaluate_alerts(ws)
        result = deliver_alerts(report, email=args.email, webhook=args.webhook)
        print(json.dumps({"alert_count": report.get("active_count", 0), **result}, indent=2))
        return 0
    if args.action == "metrics":
        from .ops_console import collect_metrics, prometheus_text
        metrics = collect_metrics(ws)
        output = json.dumps(metrics, indent=2) + "\n" if args.format == "json" else prometheus_text(metrics)
        if args.out:
            target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(output, encoding="utf-8")
            print(f"Metrics written: {target}")
        else:
            print(output, end="")
        return 0
    if args.action == "status":
        report = operations.health_snapshot(ws)
        print(json.dumps(report, indent=2))
        return 1 if report["status"] == "fail" else 0
    if args.action == "backup-status":
        print(json.dumps(operations.backup_status(ws), indent=2))
        return 0
    if args.action == "monitor":
        from .monitoring import monitoring_snapshot
        report = monitoring_snapshot(ws)
        print(json.dumps(report, indent=2))
        return 1 if report.get("status") == "fail" else 0
    if args.action == "recovery-report":
        from .monitoring import recovery_report
        report = recovery_report(ws)
        print(json.dumps(report, indent=2))
        return 1 if report.get("status") in ("stale", "unknown") else 0
    if args.action == "rehearse":
        if not args.path:
            raise WorkspaceError("Provide a compressed database backup path to rehearse")
        from .monitoring import rehearse_database_backup
        report = rehearse_database_backup(args.path)
        print(json.dumps(report, indent=2))
        return 0 if report.get("status") in ("passed", "preflight_only") else 1
    if args.action == "configure":
        report = operations.configure_backup_policy(ws, every_hours=args.every_hours, keep=args.keep,
            workspace_snapshot=not args.no_workspace_snapshot, verify=not args.no_verify)
        print(json.dumps(report, indent=2))
        print("Schedule this command with cron/systemd: velora ops run-scheduled")
        return 0
    if args.action == "run-scheduled":
        report = operations.run_scheduled_backups(ws, password=os.environ.get("VELORA_BACKUP_PASSWORD"), force=args.force)
        print(json.dumps(report, indent=2, default=str))
        return 1 if report.get("status") in ("failed", "partial") else 0
    if args.action == "backup":
        if os.environ.get("VELORA_BACKUP_PASSWORD"):                 # unattended (cron, a service): no prompts
            password = os.environ["VELORA_BACKUP_PASSWORD"]
        else:
            password = _password(None, "Backup encryption password")
            confirm = getpass.getpass("Confirm backup encryption password: ")
            if password != confirm:
                raise WorkspaceError("Backup passwords do not match")
        path = operations.create_encrypted_backup(ws, password, args.path, include_files=False if args.no_files else None)
        print(f"Encrypted workspace backup created: {path}")
        if (ws.root / "files").is_dir():
            what = operations.verify_encrypted_backup(path, password)
            print(f"Uploaded files: {what['attachments']} included" if what["files_included"] else "WARNING: uploaded files are NOT in this backup (too large for memory, or --no-files): back up the files/ folder separately")
        return 0
    if args.action == "prune":
        removed = operations.prune_backups(ws, args.keep)
        print(f"Removed {len(removed)} expired backup(s)")
        return 0
    raise WorkspaceError(f"Unknown ops action: {args.action}")        # never fall through to a destructive default


def _cmd_readiness(args):
    from .platform_readiness import readiness_report, operational_assurance_report
    ws = _need_workspace(args)
    report = readiness_report(ws)
    report["operational_assurance"] = operational_assurance_report(ws)
    print(json.dumps(report, indent=2))
    return 1 if report["overall"] == "fail" or report["operational_assurance"]["overall"] == "fail" else 0


def _cmd_manifest(args):
    from .platform_readiness import write_deployment_manifest, verify_deployment_manifest
    ws = _need_workspace(args)
    if args.action == "create":
        path = write_deployment_manifest(ws, args.path)
        print(f"Deployment manifest created: {path}")
        return 0
    path = Path(args.path) if args.path else ws.root / "config" / "deployment-manifest.json"
    report = verify_deployment_manifest(ws, path)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


def _cmd_layout(args):
    from . import layout
    if args.write_docs:
        Path(args.write_docs).write_text(layout.render_doc())
        print(f"Wrote {args.write_docs}")
        return 0
    ws = _need_workspace(args)
    if args.fix:
        done = layout.tidy(ws)
        from .controlplane import ControlPlane
        if ControlPlane.exists(ws):
            plane = ControlPlane.open(ws)
            n = plane.normalize_company_paths()
            if n:
                done.append(f"made {n} company database path(s) relative")
            plane.dispose()
            done += layout.secure(ws)
        print("Fixed:\n  " + "\n  ".join(done) if done else "Nothing needed fixing.")
        print()
    print(layout.render_tree(ws))
    findings = layout.check(ws)
    print()
    if not findings:
        print("Everything is where it should be.")
    for f in findings:
        print(f"  [{f['severity']}] {f['message']}" + (f"\n         fix: {f['fix']}" if f['severity'] == 'warn' else ""))
    return 1 if any(f["severity"] == "warn" for f in findings) else 0


def _cmd_doctor(args):
    from .upgrade import doctor
    checks = doctor.run_checks(Workspace.discover(args.workspace))
    print(doctor.format_report(checks))
    return 1 if any(c["status"] == "fail" for c in checks) else 0


def _cmd_quickstart(args):
    from . import quickstart as qs
    email, company = args.email, args.company
    if qs.is_interactive():
        email = email or input("Administrator email: ").strip()
        company = company or (input("Your company name [My Company]: ").strip() or "My Company")
    company = company or "My Company"
    kw = {}
    if args.db == "postgres":
        kw = {"db_host": args.db_host, "db_port": args.db_port, "root_user": args.db_root_user, "root_password": args.db_root_password}
    res = qs.quickstart(args.path, email=email or "", password=args.password, company=company, sample=not args.no_sample, db=args.db, db_kwargs=kw, log=print)
    url = f"http://localhost:{args.port}"
    print(f"\nAll set.\n  Open     {url}\n  Sign in  {res['email']}" + (f"\n  Password {res['password']}   <- shown ONCE: save it now" if res["generated_password"] else ""))
    print(f"  Tutorial {url.rstrip('/')}/tutorial      (and a welcome page that explains what was just set up opens the first time you sign in)")
    print(f"  Keep     {res['workspace']}/platform/master.key safe (it encrypts your company database credentials)")
    if args.db == "sqlite":
        print("  Note     SQLite is for trying things out. For real use: velora quickstart --db postgres ...")
    if args.no_start:
        print(f"\nStart later with:  cd {args.path} && velora start")
        return
    if args.open:
        qs.open_browser(url)
    os.chdir(res["workspace"])
    args.workspace = res["workspace"]
    args.site = None
    args.host = "127.0.0.1"
    _cmd_start(args)


def _cmd_start(args):
    import uvicorn

    from . import lifecycle, worker
    from .api import create_app
    ws = Workspace.discover(args.workspace)
    stop = threading.Event()
    bg = None
    try:
        if ws is not None:
            from .controlplane import ControlPlane
            from . import layout
            ws.activate()
            tidied = layout.tidy(ws)                                          # older layout moved, permissions repaired, README/.gitignore refreshed: nothing for anyone to remember
            if ControlPlane.exists(ws):
                _p = ControlPlane.open(ws)
                n = _p.normalize_company_paths()                              # company databases recorded with an absolute path become relative (the folder can then be moved)
                if n:
                    tidied.append(f"made {n} company database path(s) relative")
                    layout.secure(ws)
            if tidied:
                print("Tidied the workspace: " + "; ".join(tidied))
            if (getattr(args, "auto_upgrade", None) is None and ws.common_config().get("auto_upgrade")) or getattr(args, "auto_upgrade", None):
                rep = lifecycle.upgrade_if_needed(ws, log=print)               # the code is newer than a database: upgrade it now instead of showing 'upgrade pending'
                if rep and rep["status"] not in ("success", "up_to_date"):
                    print("The automatic upgrade did not complete (see above); the server starts in 'upgrade pending' mode. Fix the problem, then run `velora update`.")
            if ControlPlane.exists(ws) and not args.site:
                plane = ControlPlane.open(ws)
                print(f"Serving workspace {ws.root} in PLATFORM mode (sign-in required; {len(plane.registry.list_companies())} companies)  |  Desk UI: {'yes' if resolve_desk_path(ws) else 'not found'}")
                app = create_app(auto_init=False, workspace=ws, plane=plane)
            else:
                if args.site:
                    ws.current_site(args.site)                       # validate early
                print(f"Serving workspace {ws.root} with sites: {', '.join(ws.sites()) or 'none'}  |  Desk UI: {'yes' if resolve_desk_path(ws) else 'not found'}")
                app = create_app(auto_init=False, workspace=ws, site=args.site)
            if not getattr(args, "no_worker", False):
                bg = worker.start_background(ws, stop, log=print)
        else:
            from . import runtime
            runtime.init()
            app = create_app(auto_init=False)
            if not getattr(args, "no_worker", False):
                bg = worker.start_background(None, stop, log=print)
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        stop.set()                                                          # the background worker finishes its current task and exits
        if bg is not None:
            bg.join(timeout=10)


COMMANDS = {
    "layout": _cmd_layout, "init": _cmd_init, "new-site": _cmd_new_site, "drop-site": _cmd_drop_site, "list-sites": _cmd_list_sites,
    "use": lambda a: (_need_workspace(a).use(a.name), print(f"Default site is now {a.name}")),
    "new-app": _cmd_new_app, "new-doctype": _cmd_new_doctype, "get-app": _cmd_get_app, "list-apps": _cmd_list_apps,
    "install-app": _cmd_install_app, "uninstall-app": _cmd_uninstall_app, "migrate": _cmd_migrate,
    "validate-app": _cmd_validate_app, "marketplace": _cmd_marketplace, "deploy": _cmd_deploy, "export-app": _cmd_export_app, "import-app-package": _cmd_import_app_package,
    "new-doctypes": _cmd_new_doctypes, "pg": _cmd_pg, "worker": _cmd_worker, "import-data": _cmd_import_data, "export-data": _cmd_export_data, "import-template": _cmd_import_template, "domain": _cmd_domain, "apply-update": _cmd_apply_update, "deps": _cmd_deps, "quickstart": _cmd_quickstart, "doctor": _cmd_doctor, "ops": _cmd_ops, "readiness": _cmd_readiness, "manifest": _cmd_manifest, "upgrade": _cmd_upgrade, "upgrade-plan": _cmd_upgrade_plan, "update": _cmd_update, "restore": _cmd_restore, "maintenance": _cmd_maintenance,
    "platform": _cmd_platform, "tenant": _cmd_tenant, "company": _cmd_company, "user": _cmd_user, "doctypes": _cmd_doctypes, "backup": _cmd_backup, "start": _cmd_start, "serve": _cmd_start,
}


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        rc = COMMANDS[args.cmd](args)
        return rc if isinstance(rc, int) else 0
    except WorkspaceError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except OSError as e:                                   # unwritable path, disk full, permission denied ...
        print(f"Error: {e.strerror or e}{' (' + str(e.filename) + ')' if e.filename else ''}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        from . import dbpool
        from .exceptions import VeloraError
        if dbpool.is_connection_exhaustion(e) and not os.environ.get("VELORA_DEBUG"):   # one readable sentence, not a 150-line traceback
            print(f"Error: {dbpool.EXHAUSTION_MESSAGE}", file=sys.stderr)
            return 1
        if isinstance(e, VeloraError):
            print(f"Error: {e}", file=sys.stderr)
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
