"""One-click updates from a drop folder.

Put new wheels (``velora-1.6.7-...whl``, ``velora_erp-2.79.0-...whl``) in ``<workspace>/updates/``. The Update Centre lists what is newer
than what is installed and runs the whole procedure in a background process that survives a service restart:

    maintenance on -> install wheels -> upgrade every database (takes its own backup first) -> install-app on every company -> maintenance off -> restart

Every step is written to ``updates/jobs/<id>.json`` so the screen can follow it, even across the restart. Nothing is deleted.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from ..exceptions import ValidationError
from .versions import compare

DROP_NAME = "updates"
WHEEL_RE = re.compile(r"^(?P<dist>[A-Za-z0-9_.]+)-(?P<version>[0-9][^-]*)-[^-]+-[^-]+-[^-]+\.whl$")
MAX_UPLOAD = 300 * 1024 * 1024


def drop_dir(ws) -> Path:
    d = Path(ws.root) / DROP_NAME
    (d / "jobs").mkdir(parents=True, exist_ok=True)
    return d


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def installed_version(dist: str) -> str | None:
    for candidate in (dist, dist.replace("_", "-")):
        try:
            return metadata.version(candidate)
        except metadata.PackageNotFoundError:
            continue
    return None


def scan(ws) -> list[dict]:
    """Wheels waiting in the drop folder, with what is installed now and whether the file is newer."""
    out = []
    for p in sorted(drop_dir(ws).glob("*.whl")):
        m = WHEEL_RE.match(p.name)
        if not m:
            out.append({"file": p.name, "package": None, "version": None, "installed": None, "newer": False, "note": "not a valid wheel file name"})
            continue
        dist, ver = m.group("dist"), m.group("version")
        have = installed_version(dist)
        out.append({"file": p.name, "package": dist.replace("_", "-"), "version": ver, "installed": have, "newer": have is None or compare(ver, have) > 0,
                    "size": p.stat().st_size, "note": ""})
    # keep only the newest file per package
    best: dict = {}
    for r in out:
        k = r["package"] or r["file"]
        if k not in best or (r["version"] and best[k]["version"] and compare(r["version"], best[k]["version"]) > 0):
            best[k] = r
    return sorted(best.values(), key=lambda r: (r["package"] != "velora", r["file"]))


def save_upload(ws, filename: str, data: bytes) -> dict:
    name = os.path.basename(str(filename or "").replace("\\", "/"))
    if not name.lower().endswith(".whl") or not WHEEL_RE.match(name):
        raise ValidationError("Upload a Python wheel such as velora-1.6.7-py3-none-any.whl or velora_erp-2.79.0-py3-none-any.whl.")
    if not data or len(data) > MAX_UPLOAD:
        raise ValidationError("The file is empty or larger than 300 MB.")
    if not zipfile.is_zipfile(__import__("io").BytesIO(data)):
        raise ValidationError("That file is not a valid wheel (it is not a zip archive).")
    target = drop_dir(ws) / name
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return {"file": name, "size": len(data)}


# ---- jobs ------------------------------------------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _job_file(ws, job_id: str) -> Path:
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}", job_id):
        raise ValidationError("Unknown update job")
    return drop_dir(ws) / "jobs" / f"{job_id}.json"


def read_job(ws, job_id: str) -> dict | None:
    f = _job_file(ws, job_id)
    return json.loads(f.read_text()) if f.exists() else None


def latest_job(ws) -> dict | None:
    files = sorted((drop_dir(ws) / "jobs").glob("*.json"))
    return json.loads(files[-1].read_text()) if files else None


def running_job(ws) -> dict | None:
    j = latest_job(ws)
    if j and j.get("state") == "running":
        # a worker that died leaves 'running' behind: treat a job with no heartbeat for 20 minutes as dead
        if time.time() - float(j.get("heartbeat", 0)) < 1200:
            return j
    return None


class Job:
    def __init__(self, ws, job_id: str, doc: dict | None = None):
        self.ws, self.id = ws, job_id
        self.doc = doc or {"id": job_id, "state": "running", "started": _now(), "steps": [], "log": [], "heartbeat": time.time()}

    def save(self):
        self.doc["heartbeat"] = time.time()
        f = _job_file(self.ws, self.id)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc, indent=1))
        tmp.replace(f)

    def log(self, line: str):
        self.doc["log"] = (self.doc["log"] + [f"{_now()}  {line}"])[-400:]
        self.save()

    def step(self, name: str, state: str, detail: str = ""):
        steps = [s for s in self.doc["steps"] if s["name"] != name]
        steps.append({"name": name, "state": state, "detail": detail})
        order = [s["name"] for s in self.doc["steps"]]
        steps.sort(key=lambda s: order.index(s["name"]) if s["name"] in order else 999)
        self.doc["steps"] = steps
        self.save()


def start(ws, *, actor: str = "", spawn=None) -> str:
    """Begin an update in a detached worker process and return its job id. Refuses to start a second one."""
    if running_job(ws):
        raise ValidationError("An update is already running. Wait for it to finish.")
    todo = [r for r in scan(ws) if r["newer"] and r["package"]]
    if not todo:
        raise ValidationError("There is nothing newer than what is installed in the updates folder.")
    job_id = time.strftime("%Y%m%d-%H%M%S")
    job = Job(ws, job_id)
    job.doc.update(actor=actor, files=[r["file"] for r in todo], plan=[f"{r['package']} {r['installed'] or '(new)'} -> {r['version']}" for r in todo])
    job.save()
    cmd = [sys.executable, "-m", "velora.upgrade.dropfolder", str(ws.root), job_id]
    log_file = drop_dir(ws) / "jobs" / f"{job_id}.out"
    if spawn:
        spawn(cmd)
    else:
        with open(log_file, "ab") as out:
            subprocess.Popen(cmd, stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return job_id


def _run(job: Job, cmd: list[str], label: str, timeout=1800) -> None:
    job.log(f"$ {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    for line in (r.stdout + r.stderr).strip().splitlines()[-25:]:
        job.log("  " + line)
    if r.returncode:
        raise RuntimeError(f"{label} failed (exit {r.returncode})")


def execute(ws, job_id: str, runner=None) -> dict:
    """The worker body: run every step, recording progress. ``runner(job, cmd, label)`` is replaceable in tests."""
    job = Job(ws, job_id, read_job(ws, job_id))
    run = runner or _run
    py = sys.executable
    velora = [py, "-m", "velora", "--workspace", str(ws.root)]
    cfg = ws.common_config().get("update", {})
    files = [str(drop_dir(ws) / f) for f in job.doc.get("files", [])]
    steps = ["Maintenance mode on", "Install new code", "Upgrade databases", "Install apps", "Maintenance mode off", "Restart"]
    for s in steps:
        job.step(s, "pending")
    try:
        job.step(steps[0], "running"); run(job, velora + ["maintenance", "on", "--message", "Updating Velora. Back in a few minutes."], steps[0]); job.step(steps[0], "done")
        job.step(steps[1], "running"); run(job, [py, "-m", "pip", "install", "--upgrade", "--no-deps", "--disable-pip-version-check", *files], steps[1]); job.step(steps[1], "done")
        job.step(steps[2], "running"); run(job, velora + ["upgrade"], steps[2]); job.step(steps[2], "done")
        job.step(steps[3], "running")
        for app in ws.apps():
            run(job, velora + ["install-app", app], f"install-app {app}")
        job.step(steps[3], "done")
        job.step(steps[4], "running"); run(job, velora + ["maintenance", "off"], steps[4]); job.step(steps[4], "done")
        restart = cfg.get("restart_command")
        if restart:
            job.step(steps[5], "running"); job.doc.update(state="done", finished=_now()); job.save()
            run(job, ["/bin/sh", "-c", restart], steps[5]); job.step(steps[5], "done")
        else:
            job.step(steps[5], "skipped", "No restart command is configured. Restart the Velora service once to load the new code.")
        job.doc.update(state="done", finished=_now()); job.save()
        job.log("Update finished.")
    except Exception as exc:  # noqa: BLE001
        job.doc.update(state="failed", finished=_now(), error=str(exc)); job.save()
        job.log(f"STOPPED: {exc}. Maintenance mode was left ON on purpose. Fix the cause, or restore the backup taken at the start of the upgrade, then turn maintenance off.")
    return job.doc


if __name__ == "__main__":                                                    # python -m velora.upgrade.dropfolder <workspace> <job id>
    from ..workspace import Workspace
    _ws = Workspace(Path(sys.argv[1]))
    execute(_ws, sys.argv[2])
