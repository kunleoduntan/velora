"""A plain-language record of what the lifecycle commands did: installed, updated, upgraded, app added/removed, domain added.
The welcome page shows the latest entry ("here is what just happened"), and the history is a changelog for the administrator."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

MAX_EVENTS = 50
KINDS = ("install", "update", "upgrade", "install-app", "uninstall-app", "domain")


def _file(ws) -> Path:
    return Path(ws.events_file)


def _load(ws) -> list[dict]:
    try:
        data = json.loads(_file(ws).read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []                                                    # missing or damaged: start a fresh history rather than fail a lifecycle command


def _step(s) -> dict:
    return {"text": str(s["text"]), "ok": bool(s.get("ok", True))} if isinstance(s, dict) else {"text": str(s), "ok": True}


def record(ws, kind: str, title: str, steps: list | None = None, *, ok: bool = True, **details) -> dict:
    """Append one event. Never raises: keeping a history must not make an install or update fail."""
    ev = {"id": uuid.uuid4().hex[:12], "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, "title": title, "ok": ok,
          "version": __version__, "steps": [_step(s) for s in (steps or [])], **{k: v for k, v in details.items() if v is not None}}
    try:
        events = (_load(ws) + [ev])[-MAX_EVENTS:]
        f = _file(ws)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(events, indent=2, default=str))
        os.replace(tmp, f)
    except OSError:
        pass
    return ev


def recent(ws, limit: int = 10) -> list[dict]:
    """Newest first."""
    return list(reversed(_load(ws)))[:limit] if ws is not None else []


def from_update_report(rep: dict) -> tuple[str, bool, list[dict], dict]:
    """(title, ok, steps, details) describing an update/upgrade report in plain words."""
    status = rep.get("status", "")
    code = rep.get("code") or {}
    fw = code.get("framework")
    up = rep.get("upgrade") or {}
    steps: list[dict] = []
    if fw:
        steps.append({"text": f"Updated Velora from {fw['from']} to {fw['to']}", "ok": True})
    for a in code.get("apps", []):
        steps.append({"text": f"Updated the app {a['name']} ({a.get('commits', 0)} change(s))", "ok": True})
    if rep.get("packages"):
        steps.append({"text": f"Installed or updated Python packages: {', '.join(rep['packages'])}", "ok": True})
    if up.get("snapshot"):
        steps.append({"text": f"Backed up every database first ({up['snapshot']})", "ok": True})
    done = [t for t in up.get("targets", []) if t.get("status") in ("upgraded",)]
    cur = [t for t in up.get("targets", []) if t.get("status") == "up_to_date"]
    bad = [t for t in up.get("targets", []) if t.get("status", "").startswith("failed")]
    if done:
        steps.append({"text": f"Upgraded {len(done)} database(s): {', '.join(t['label'] for t in done)}", "ok": True})
    if cur and not done and not bad:
        steps.append({"text": f"Checked {len(cur)} database(s): already current", "ok": True})
    for t in bad:
        steps.append({"text": f"{t['label']} could not be upgraded: {t.get('error', 'see the log')}", "ok": False})
    for f in rep.get("features", []):
        steps.append({"text": f"Turned on {f['app']} for {f['target']}" if f.get("status") == "installed" else f"Could not turn on {f['app']} for {f['target']}: {f.get('error', '')}", "ok": f.get("status") == "installed"})
    rs = rep.get("restart")
    if rs and rs.get("ok") is True:
        steps.append({"text": "Restarted the server", "ok": True})
    elif rs and rs.get("ok") is False:
        steps.append({"text": f"Restart failed: {rs.get('output', '')}", "ok": False})
    elif rs:
        steps.append({"text": "Restart the server to use the new code (no restart command is configured)", "ok": True})
    if status == "rolled_back":
        steps.append({"text": "Something failed, so every database and the code were put back exactly as they were", "ok": False})
    ok = status in ("success", "up_to_date")
    title = {"success": "Update complete", "up_to_date": "Checked for updates: everything is current", "rolled_back": "Update failed and was undone", "partial": "Update finished partially",
             "failed": "Update failed"}.get(status, f"Update: {status}")
    if status in ("success", "up_to_date") and (fw or code.get("apps") or rep.get("packages")):
        title = "Update complete"                                         # new CODE was installed even if every database was already current: that is not "nothing happened"
    return title, ok, steps, {"from_version": fw["from"] if fw else None, "to_version": fw["to"] if fw else None}
