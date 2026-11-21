"""A small scheduler: apps list functions to run periodically in their hooks.py

    scheduler_events = {
        "every_tick":   ["myapp.jobs.drain_queue"],     # every worker loop (seconds): queues
        "every_minute": ["myapp.jobs.escalate"],
        "hourly":       ["myapp.jobs.digests"],
        "daily":        ["myapp.jobs.scan_dates"],
    }

`run_due()` runs the due tasks of the CURRENT database. The last-run time is claimed with a single atomic UPDATE, so any number of workers can run side by side
and a frequency still runs once per interval. Each task runs in its own transaction (unless it sets `fn.manages_transactions = True`) and a failing task never stops the others.
"""
from __future__ import annotations

import importlib
import traceback
from datetime import datetime, timedelta

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from . import db
from .db.system import scheduler_state
from .document.document import now as _now
from .meta.registry import registry

INTERVALS = {"every_tick": 0, "every_minute": 60, "hourly": 3600, "daily": 86400}


def claim(freq: str, now: datetime, owner: str = "worker") -> bool:
    """True if THIS caller may run `freq` now (it is due, and nobody else claimed it first)."""
    interval = INTERVALS[freq]
    if interval == 0:
        return True
    t = scheduler_state
    with db.transaction() as conn:
        if conn.execute(update(t).where(t.c.key == freq, t.c.last_run <= now - timedelta(seconds=interval)).values(last_run=now, owner=owner)).rowcount:
            return True
        if conn.execute(select(t.c.key).where(t.c.key == freq)).first():
            return False                                                # ran recently
        try:
            with conn.begin_nested():
                conn.execute(insert(t).values(key=freq, last_run=now, owner=owner))
            return True
        except IntegrityError:                                          # another worker inserted it first
            return False


def _resolve(path: str):
    mod, _, fn = path.rpartition(".")
    return getattr(importlib.import_module(mod), fn)


def run_due(now: datetime | None = None, owner: str = "worker") -> list[dict]:
    """Run every due task of the current site. Returns one result per task: {freq, task, ok, error?}."""
    now = now or _now()
    out = []
    for freq in INTERVALS:
        tasks = registry.scheduler_tasks(freq)
        if not tasks or not claim(freq, now, owner):
            continue
        for path in tasks:
            try:
                fn = _resolve(path)
                if getattr(fn, "manages_transactions", False):
                    fn()                                            # the task commits in steps itself (e.g. after every message it sends)
                else:
                    with db.transaction():
                        fn()
                out.append({"freq": freq, "task": path, "ok": True})
            except Exception as e:  # noqa: BLE001 - one broken job must not stop the rest
                out.append({"freq": freq, "task": path, "ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=4)})
    return out
