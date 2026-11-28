"""`velora doctor`: check that an installation is healthy, and say exactly how to fix what is not."""
from __future__ import annotations

import importlib
import os
import shutil
import sys

from ..workspace import Workspace
from . import maintenance
from .versions import code_version

OK, WARN, FAIL = "ok", "warn", "fail"


def _worker_age(t):
    """Seconds since the background worker last ran for this company; None if never; 'n/a' if nothing installed needs a worker."""
    from sqlalchemy import select

    from .. import db, site as site_mod
    from ..db.system import scheduler_state
    from ..document.document import now
    from ..meta.registry import registry
    with site_mod.use(t.site):
        t.site.load()
        if not registry.scheduler_tasks("every_minute"):
            return "n/a"
        with db.transaction() as c:
            last = c.execute(select(scheduler_state.c.last_run).where(scheduler_state.c.key == "every_minute")).scalar()
    return None if last is None else (now() - last).total_seconds()


def run_checks(ws: Workspace | None) -> list[dict]:
    out: list[dict] = []
    add = lambda name, status, detail="", fix="": out.append({"check": name, "status": status, "detail": detail, "fix": fix})

    v = sys.version_info
    from .. import compat
    pst, pdetail, pfix = compat.python_status(v)
    add("Python", OK if pst == "ok" else FAIL, pdetail, pfix)
    osi = compat.current_os()
    add("Operating system", {"supported": OK, "works": OK, "untested": WARN, "eol": WARN}[osi["status"]], f"{osi['name']} ({osi['status']})", osi["note"] if osi["status"] in ("eol", "untested") else "")
    add("Velora", OK, code_version())
    for mod, why in (("sqlalchemy", "database layer"), ("fastapi", "API"), ("uvicorn", "web server"), ("cryptography", "credential encryption"), ("xlsxwriter", "Excel export")):
        try:
            importlib.import_module(mod)
            add(f"Package {mod}", OK, why)
        except ImportError:
            add(f"Package {mod}", FAIL, f"missing ({why})", f"pip install {mod}")
    try:
        importlib.import_module("psycopg")
        add("Package psycopg", OK, "PostgreSQL driver")
    except ImportError:
        add("Package psycopg", WARN, "PostgreSQL driver not installed", 'pip install "velora[postgres]"  (only needed for PostgreSQL)')
    for tool, why in (("git", "get-app / update"), ("pg_dump", "PostgreSQL backups"), ("psql", "PostgreSQL restore")):
        add(f"Tool {tool}", OK if shutil.which(tool) else WARN, why if shutil.which(tool) else f"not found ({why})",
            "" if shutil.which(tool) else "install it (e.g. apt install postgresql-client git)" if tool != "git" else "apt install git")

    from .. import optional
    for name in ("data", "pdf", "ml", "forecast", "markets", "sftp", "security"):
        st = optional.status(name)
        add(f"Optional: {name}", OK, f"{st['installed']}/{st['total']} installed - {st['description']}" + ("" if st["complete"] else f'  (pip install "velora[{name}]")'))

    if ws is None:
        add("Workspace", FAIL, "not inside a Velora workspace", "run `velora init <dir>` (or `velora quickstart`), or cd into one")
        return out
    add("Workspace", OK, str(ws.root))
    from .. import layout
    findings = layout.check(ws)
    warns = [f for f in findings if f["severity"] == "warn"]
    add("Folder layout", WARN if warns else OK, "; ".join(f["message"] for f in (warns or findings))[:300] or "everything is where it should be (see `velora layout`)",
        "velora layout --fix" if findings else "")
    free = shutil.disk_usage(ws.root).free / 1e9
    add("Disk space", OK if free >= 2 else WARN if free >= 0.5 else FAIL, f"{free:.1f} GB free", "" if free >= 2 else "an upgrade needs room for backups: free some disk space")
    for d in ("backups", "logs"):
        p = ws.root / d
        p.mkdir(exist_ok=True)
        add(f"Writable {d}/", OK if os.access(p, os.W_OK) else FAIL, str(p), "" if os.access(p, os.W_OK) else f"chmod u+w {p}")
    if maintenance.status(ws):
        add("Maintenance mode", WARN, "is ON (an upgrade is running, or crashed)", "if no upgrade is running: velora maintenance off")
    lock = ws.root / ".upgrade.lock"
    if lock.exists():
        add("Upgrade lock", WARN, f"{lock.name} exists", "if no upgrade is running, delete it")
    ws.activate()

    from ..controlplane import ControlPlane
    from .engine import collect_targets, inspect_target, needs_upgrade
    if ControlPlane.exists(ws):
        mk = ws.root / "platform" / "master.key"
        if os.environ.get("VELORA_MASTER_KEY"):
            add("Master key", OK, "from VELORA_MASTER_KEY")
        elif mk.exists():
            mode = oct(mk.stat().st_mode & 0o777)
            add("Master key", OK if mode == "0o600" else WARN, f"platform/master.key ({mode})",
                "" if mode == "0o600" else f"chmod 600 {mk}   (and back it up SEPARATELY from the databases)")
        else:
            add("Master key", FAIL, "missing", "restore platform/master.key from your backup - company credentials cannot be decrypted without it")
    try:
        targets = collect_targets(ws)
    except Exception as e:  # noqa: BLE001
        add("Databases", FAIL, str(e).splitlines()[0][:200], "check the database settings / that PostgreSQL is running")
        return out
    for t in targets:
        try:
            info = inspect_target(t)
        except Exception as e:  # noqa: BLE001
            add(t.label, FAIL, str(e).splitlines()[0][:200], "check the database is reachable and the app code is installed")
            continue
        if needs_upgrade(info):
            bits = [f"version {info['version'] or 'unknown'}"] + ([f"{len(info['schema'])} schema change(s)"] if info["schema"] else []) + ([f"{len(info['patches'])} patch(es)"] if info["patches"] else [])
            add(t.label, WARN, "needs upgrade: " + ", ".join(bits), "run `velora upgrade`")
        else:
            add(t.label, OK, f"up to date (version {info['version']})")
        for w in info["warnings"]:
            add(f"{t.label} schema", WARN, w, "ship a data patch for this change")
    seen_servers = set()
    for t in targets:
        if t.site is None:                                  # the control plane has no site object of its own
            continue
        try:
            eng = t.site.engine
            if eng.dialect.name != "postgresql":
                continue
            server = f"{eng.url.host}:{eng.url.port or 5432}"
            if server in seen_servers:
                continue
            seen_servers.add(server)
            from .. import pg as pgmod
            from .. import site as site_mod
            with site_mod.use(t.site):                      # status() compares the database with what the installed apps declare, so it needs this company's registry
                t.site.load()
                with eng.connect() as conn:
                    st = pgmod.status(conn)
            add(f"PostgreSQL {server}", WARN if st["advice"] else OK, f"version {st['version']}" + (f"; {len(st['advice'])} suggestion(s)" if st["advice"] else ""),
                "run `velora pg status` for the details" if st["advice"] else "")
        except Exception as e:  # noqa: BLE001 - a doctor must report, not crash
            add(f"PostgreSQL {t.label}", WARN, f"could not inspect: {type(e).__name__}", "")

    for t in targets:
        if t.kind == "control_plane" or t.site is None:
            continue
        try:
            age = _worker_age(t)
        except Exception:  # noqa: BLE001
            continue
        if age == "n/a":
            continue
        if age is None or age > 300:
            add(f"Background worker {t.label}", WARN, "no worker has run for this company" + (f" in {int(age // 60)} minutes" if age else " yet"),
                "`velora start` runs the worker inside the server; or run `velora worker` as its own service")
        else:
            add(f"Background worker {t.label}", OK, f"last ran {int(age)} s ago")

    for app in ws.apps():
        try:
            reqs = getattr(importlib.import_module(f"{app}.hooks"), "required_packages", [])
        except Exception:  # noqa: BLE001 - an app without hooks simply declares nothing
            continue
        problems = optional.check_packages(reqs)
        if problems:
            add(f"Packages for {app}", FAIL, "; ".join(problems), f"velora deps install --app {app}")
        elif reqs:
            add(f"Packages for {app}", OK, f"{len(reqs)} required package(s) ready")
    return out


def format_report(checks: list[dict]) -> str:
    mark = {OK: "ok  ", WARN: "WARN", FAIL: "FAIL"}
    lines = [f"[{mark[c['status']]}] {c['check']:<26} {c['detail']}" + (f"\n         -> {c['fix']}" if c["fix"] and c["status"] != OK else "") for c in checks]
    bad, warn = sum(c["status"] == FAIL for c in checks), sum(c["status"] == WARN for c in checks)
    lines.append(f"\n{len(checks)} checks: {len(checks) - bad - warn} ok, {warn} warning(s), {bad} failure(s)")
    return "\n".join(lines)
