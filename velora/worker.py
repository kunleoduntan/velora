"""`velora worker`: runs scheduled tasks for every company/site of a workspace (queues, retries, reminders, digests ...).

Safe to run several workers (the scheduler claims work atomically). It skips a company while an upgrade is running, while maintenance mode is on, or when
that company's database has not been upgraded for the installed code.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from . import site as site_mod
from .company import company_context
from .permissions import ADMINISTRATOR, session_as
from .scheduler import run_due
from .upgrade import maintenance, state
from .upgrade.engine import collect_targets
from .workspace import Workspace


def run_once(ws: Workspace, now: datetime | None = None, targets=None, log=lambda m: None) -> list[dict]:
    """One pass over all companies/sites. Returns [{target, results: [...]}]."""
    if maintenance.status(ws):
        return []
    out = []
    for t in targets if targets is not None else [x for x in collect_targets(ws) if x.kind != "control_plane"]:
        if state.check_site(t.site)[0] != "ok":
            continue
        with site_mod.use(t.site), session_as(ADMINISTRATOR):
            if t.company is not None:
                with company_context(t.company):
                    res = run_due(now)
                    from .jobs import process_due_jobs
                    job_stats = process_due_jobs(owner=f"worker:{__import__('os').getpid()}")
                    from .workflow_automation import process_due_slas
                    sla_stats = process_due_slas()
                    res.append({"freq": "jobs", "task": "velora.workflow_automation.process_due_slas",
                                "ok": True, "stats": sla_stats})
                    res.append({"freq": "jobs", "task": "velora.jobs.process_due_jobs",
                                "ok": job_stats["dead"] == 0, "stats": job_stats,
                                **({"error": "One or more background jobs entered the Dead state"} if job_stats["dead"] else {})})
            else:
                res = run_due(now)
        for r in res:
            if not r["ok"]:
                log(f"{t.label}: {r['task']} failed: {r['error']}")
        out.append({"target": t.id, "results": res})
    return out


def serve(ws: Workspace, interval: float = 5.0, log=print, should_stop=lambda: False, refresh_every: float = 60.0) -> None:
    """Loop until told to stop. The list of companies is refreshed every minute (new companies are picked up without a restart). A failing pass never ends the loop."""
    targets, loaded = None, 0.0
    log(f"Worker started (every {interval:g}s).")
    while not should_stop():
        try:
            if targets is None or time.monotonic() - loaded > refresh_every:
                targets = [x for x in collect_targets(ws) if x.kind != "control_plane"]
                loaded = time.monotonic()
            run_once(ws, targets=targets, log=log)
        except Exception as e:  # noqa: BLE001 - a bad pass is logged; the worker keeps going
            log(f"worker pass failed: {type(e).__name__}: {e}")
            targets = None
        for _ in range(int(interval * 10)):
            if should_stop():
                break
            time.sleep(0.1)


def serve_site(interval: float = 5.0, log=print, should_stop=lambda: False) -> None:
    """The same for a single database configured through environment variables (no workspace)."""
    from .scheduler import run_due
    log(f"Worker started (every {interval:g}s).")
    while not should_stop():
        try:
            with session_as(ADMINISTRATOR):
                for r in run_due():
                    if not r["ok"]:
                        log(f"{r['task']} failed: {r['error']}")
        except Exception as e:  # noqa: BLE001
            log(f"worker pass failed: {type(e).__name__}: {e}")
        for _ in range(int(interval * 10)):
            if should_stop():
                break
            time.sleep(0.1)


def start_background(ws: Workspace | None, stop: threading.Event, interval: float = 5.0, log=print) -> threading.Thread:
    """Run the worker inside the server process, so there is no second service to install or remember. `stop.set()` ends it."""
    def run():
        if ws is not None:
            serve(ws, interval, log, stop.is_set)
        else:
            serve_site(interval, log, stop.is_set)
    t = threading.Thread(target=run, name="velora-worker", daemon=True)
    t.start()
    return t
