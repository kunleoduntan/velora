"""`velora update`: fetch new code (apps from git, the framework from pip), then upgrade the data - and undo everything if it fails.

    check → maintenance ON → remember code state (git SHAs, framework version) → pull apps / pip upgrade velora → install app dependencies
          → run `velora upgrade` in a FRESH process (so the NEW code does the migration) → restart hook → maintenance OFF
    on any failure: restore the code (git reset --hard <sha>, pip reinstall the previous version); `velora upgrade` already restored the data.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ..workspace import Workspace, WorkspaceError
from . import maintenance
from .engine import UpgradeEngine, UpgradeError, upgrade_lock
from .versions import app_version, code_version, compare

_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _clear_bytecode(app_dir: Path) -> int:
    """Delete an app's __pycache__ folders. Python reuses a .pyc whenever the source's mtime (whole seconds) and size match, so a file that
    `git pull` rewrote within the same second with the same length would silently keep running its OLD code."""
    n = 0
    for d in app_dir.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    return n


def _git(app_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(app_dir), *args], timeout=300)


# ---- framework source -----------------------------------------------------------------------------------------------
def pip_target(source: str | None) -> tuple[list[str], str] | None:
    """(extra pip args, requirement) for a source: PyPI spec, wheel file, wheel directory or git URL."""
    if not source:
        return None
    p = Path(source)
    if source.endswith(".whl") and p.is_file():
        return ["--find-links", str(p.parent)], str(p.resolve())
    if p.is_dir():
        return ["--find-links", str(p.resolve())], "velora"
    return [], source


def _wheel_version(path: str) -> str | None:
    m = re.match(r"velora-([^-]+)-", Path(path).name)
    return m.group(1) if m else None


def framework_latest(source: str | None) -> str | None:
    """The version `pip install --upgrade` WOULD install from `source`, or None if nothing newer."""
    t = pip_target(source)
    if not t:
        return None
    extra, req = t
    if req.endswith(".whl"):
        v = _wheel_version(req)
        return v if v and compare(v, code_version()) > 0 else None
    r = _run([sys.executable, "-m", "pip", "install", "--dry-run", "--no-deps", "--upgrade", "--disable-pip-version-check", *extra, req])
    m = re.search(r"Would install ([^\n]*)", r.stdout)
    if not m:
        return None
    mm = re.search(r"velora-([0-9][^\s]*)", m.group(1))
    return mm.group(1) if mm and compare(mm.group(1), code_version()) > 0 else None


# ---- apps --------------------------------------------------------------------------------------------------------------
def app_status(ws: Workspace, app: str, fetch: bool = True) -> dict:
    d = ws.app_path(app)
    info = {"name": app, "version": app_version(app), "repo": False, "behind": 0, "dirty": False, "latest": None, "sha": None, "branch": None, "note": ""}
    if not (d / ".git").exists() or _git(d, "rev-parse", "--is-inside-work-tree").returncode:
        info["note"] = "not a git checkout"
        return info
    info.update(repo=True, sha=_git(d, "rev-parse", "HEAD").stdout.strip(), branch=_git(d, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
                dirty=bool(_git(d, "status", "--porcelain").stdout.strip()))
    if _git(d, "rev-parse", "--abbrev-ref", "@{u}").returncode:
        info["note"] = "no upstream branch"
        return info
    if fetch:
        f = _git(d, "fetch", "--quiet")
        if f.returncode:
            info["note"] = f"fetch failed: {f.stderr.strip()[:120]}"
            return info
    info["behind"] = int(_git(d, "rev-list", "--count", "HEAD..@{u}").stdout.strip() or 0)
    if info["behind"]:
        init = _git(d, "show", f"@{{u}}:{app}/__init__.py")
        m = _VERSION_RE.search(init.stdout) if init.returncode == 0 else None
        info["latest"] = m.group(1) if m else None
    return info


def check_updates(ws: Workspace, framework_source: str | None = None, fetch: bool = True) -> dict:
    return {"framework": {"current": code_version(), "latest": framework_latest(framework_source) if framework_source else None,
                          "source": framework_source or "(none configured)"},
            "apps": [app_status(ws, a, fetch) for a in ws.apps()]}


def _app_requirements(ws: Workspace, app: str) -> list[str]:
    f = ws.app_path(app) / "pyproject.toml"
    if not f.exists():
        return []
    try:
        try:
            import tomllib                                   # Python 3.11+
        except ModuleNotFoundError:
            import tomli as tomllib                          # Python 3.10 (a dependency there)
        deps = tomllib.loads(f.read_text()).get("project", {}).get("dependencies", [])
    except Exception:  # noqa: BLE001 - an unparsable pyproject is reported by the pip step if it matters
        return []
    return [d for d in deps if not re.match(r"^velora([<>=!~\s\[]|$)", d.strip().lower())]


# ---- the update ------------------------------------------------------------------------------------------------------
def _update(ws: Workspace, *, framework_source: str | None = None, apps: list[str] | None = None, do_apps: bool = True, partial: bool = False,
           backup: bool = True, restart_command: str | None = None, dry_run: bool = False, log=print) -> dict:
    ws.activate()
    cfg = ws.common_config().get("update", {})
    framework_source = framework_source or cfg.get("framework_source")
    restart_command = restart_command or cfg.get("restart_command")
    report: dict = {"status": "running", "code": {"framework": None, "apps": []}, "upgrade": None, "restart": None}

    chosen = [a for a in (apps or ws.apps())] if do_apps else []
    unknown = [a for a in chosen if a not in ws.apps()]
    if unknown:
        raise WorkspaceError(f"Not in this workspace: {', '.join(unknown)}")

    log("Checking for updates ...")
    statuses = {a: app_status(ws, a) for a in chosen}
    fw_latest = framework_latest(framework_source) if framework_source else None
    blocked = [s for s in statuses.values() if s["behind"] and s["dirty"]]
    if blocked:
        raise WorkspaceError("These apps have uncommitted local changes, so they were NOT updated (commit or stash them first): "
                             + ", ".join(s["name"] for s in blocked))
    to_pull = [s for s in statuses.values() if s["behind"]]
    for s in statuses.values():
        if s["note"] and not s["behind"] and s["note"] not in ("no upstream branch", "not a git checkout"):
            log(f"  {s['name']}: {s['note']}")
    if dry_run:
        report.update(status="dry_run", code={"framework": {"from": code_version(), "to": fw_latest}, "apps": [{"name": s["name"], "behind": s["behind"], "to": s["latest"]} for s in to_pull]})
        report["upgrade"] = UpgradeEngine(ws, partial=partial, backup=backup, log=log).run(dry_run=True)
        return report

    if not to_pull and not fw_latest:
        log("No new code. Checking whether any data still needs upgrading ...")
        report["upgrade"] = UpgradeEngine(ws, partial=partial, backup=backup, log=log).run()
        report["status"] = report["upgrade"]["status"]
        if report["status"] in ("success", "up_to_date"):
            from ..lifecycle import ensure_default_apps
            report["features"] = ensure_default_apps(ws, ws.common_config().get("default_apps", []), log=log)       # built-in features that are configured but missing
        if report["status"] == "up_to_date" and not report.get("features"):
            log("Everything is already up to date.")
        return report

    with upgrade_lock(ws):
        # ---- remember how to go back ------------------------------------------------------------------------------
        snapshot = {"framework": code_version(), "shas": {s["name"]: s["sha"] for s in to_pull}}
        owns_maintenance = maintenance.status(ws) is None
        if owns_maintenance:
            maintenance.enable(ws, owner="update")
        try:
            try:
                if fw_latest:
                    log(f"Updating velora {code_version()} -> {fw_latest} ...")
                    extra, req = pip_target(framework_source)
                    r = _run([sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", *extra, req])
                    if r.returncode:
                        raise UpgradeError(f"pip could not install velora: {r.stderr.strip().splitlines()[-1][:300] if r.stderr.strip() else 'unknown error'}")
                    report["code"]["framework"] = {"from": snapshot["framework"], "to": fw_latest}
                for s in to_pull:
                    log(f"Updating {s['name']} ({s['version']} -> {s['latest'] or '?'}, {s['behind']} commit(s)) ...")
                    g = _git(ws.app_path(s["name"]), "pull", "--ff-only", "--quiet")
                    if g.returncode:
                        raise UpgradeError(f"git pull failed for {s['name']}: {g.stderr.strip()[:300]}")
                    _clear_bytecode(ws.app_path(s["name"]))
                    report["code"]["apps"].append({"name": s["name"], "from": s["version"], "to": s["latest"], "commits": s["behind"]})
                for s in to_pull:
                    reqs = _app_requirements(ws, s["name"])
                    if reqs:
                        r = _run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *reqs])
                        if r.returncode:
                            raise UpgradeError(f"could not install the requirements of {s['name']}: {r.stderr.strip().splitlines()[-1][:300] if r.stderr.strip() else ''}")
                # ---- the NEW code upgrades the data, in a fresh process -------------------------------------------------
                report_file = ws.root / "logs" / f"upgrade-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
                report_file.parent.mkdir(exist_ok=True)
                cmd = [sys.executable, "-m", "velora.cli", "--workspace", str(ws.root), "apply-update", "--report-file", str(report_file)]     # packages -> data -> built-in features, on the NEW code
                cmd += (["--partial"] if partial else []) + ([] if backup else ["--no-backup"])
                child = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
                for line in child.stdout.splitlines():
                    log(line)
                report["upgrade"] = json.loads(report_file.read_text()) if report_file.exists() else {"status": "failed", "error": child.stderr.strip()[-500:]}
                if child.returncode != 0 or report["upgrade"]["status"] in ("rolled_back", "failed"):
                    raise UpgradeError("The data upgrade failed; the databases were restored. " + (child.stderr.strip().splitlines()[-1] if child.stderr.strip() else ""))
            except Exception as e:  # noqa: BLE001 - restore the CODE so it matches the (restored) data
                report["error"] = str(e)
                report["code_rollback"] = _rollback_code(ws, snapshot, framework_source, log)
                report["status"] = "rolled_back"
                return report
            report["status"] = report["upgrade"]["status"]
            if restart_command:
                log(f"Restarting: {restart_command}")
                try:
                    rc = subprocess.run(restart_command, shell=True, capture_output=True, text=True, timeout=180)
                    report["restart"] = {"ok": rc.returncode == 0, "output": (rc.stderr or rc.stdout).strip()[-300:]}
                except Exception as e:  # noqa: BLE001
                    report["restart"] = {"ok": False, "output": str(e)}
            else:
                report["restart"] = {"ok": None, "output": "no restart command configured: restart the server to run the new code"}
        finally:
            if owns_maintenance:
                maintenance.disable(ws)
    return report


def _rollback_code(ws: Workspace, snapshot: dict, framework_source: str | None, log) -> dict:
    out = {"apps": [], "framework": None}
    for name, sha in snapshot["shas"].items():
        r = _git(ws.app_path(name), "reset", "--hard", "--quiet", sha)
        _clear_bytecode(ws.app_path(name))
        out["apps"].append({"name": name, "restored": r.returncode == 0, "sha": sha[:10]})
        log(f"Rolled back {name} to {sha[:10]}" if r.returncode == 0 else f"COULD NOT roll back {name}: {r.stderr.strip()[:200]}")
    if snapshot["framework"] != code_version() or framework_source:
        t = pip_target(framework_source)
        extra = t[0] if t else []
        r = _run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *extra, f"velora=={snapshot['framework']}"])
        out["framework"] = {"restored": r.returncode == 0, "version": snapshot["framework"],
                            **({} if r.returncode == 0 else {"manual": f"pip install velora=={snapshot['framework']}"})}
        log(f"Rolled back velora to {snapshot['framework']}" if r.returncode == 0 else f"COULD NOT roll back velora: run `pip install velora=={snapshot['framework']}`")
    return out


def update(ws, *args, **kwargs) -> dict:
    """Fetch new code, upgrade every database, restart (see _update). Also writes the plain-language record the welcome page shows."""
    rep = _update(ws, *args, **kwargs)
    if not kwargs.get("dry_run") and rep.get("status") != "dry_run":
        from .. import eventlog
        title, ok, steps, details = eventlog.from_update_report(rep)
        if not (rep.get("status") == "up_to_date" and not steps[1:] and not details["to_version"]):          # a no-op check is not worth an entry
            eventlog.record(ws, "update", title, steps, ok=ok, **details)
    return rep
