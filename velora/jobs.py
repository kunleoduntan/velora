"""Durable, company-local background jobs and recurring automation.

Handlers are registered by installed apps; only registered handler names can execute.
Every queue, schedule and execution record belongs to the active company's database.
"""
from __future__ import annotations

import importlib
import json
import secrets
import traceback
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import Column, DateTime, Index, Integer, JSON, MetaData, String, Table, Text, select, update

from . import db
from .document.document import now
from .exceptions import PermissionDenied, ValidationError
from .permissions import Session, get_session, session_as

_meta = MetaData()
_jobs = Table("vl_background_job", _meta,
    Column("id", String(32), primary_key=True),
    Column("handler", String(240), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("status", String(24), nullable=False),
    Column("priority", Integer, nullable=False, default=5),
    Column("run_at", DateTime, nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=5),
    Column("depends_on", JSON, nullable=False),
    Column("idempotency_key", String(180), unique=True),
    Column("created_by", String(140), nullable=False),
    Column("created_on", DateTime, nullable=False),
    Column("started_on", DateTime),
    Column("completed_on", DateTime),
    Column("claimed_by", String(120)),
    Column("claimed_at", DateTime),
    Column("result", JSON),
    Column("last_error", Text))
Index("ix_vl_job_due", _jobs.c.status, _jobs.c.run_at, _jobs.c.priority)
Index("ix_vl_job_lease", _jobs.c.status, _jobs.c.claimed_at)
_schedules = Table("vl_job_schedule", _meta,
    Column("id", String(32), primary_key=True),
    Column("label", String(160), nullable=False),
    Column("handler", String(240), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("interval_seconds", Integer, nullable=False),
    Column("next_run", DateTime, nullable=False),
    Column("active", Integer, nullable=False, default=1),
    Column("created_by", String(140), nullable=False),
    Column("created_on", DateTime, nullable=False))
Index("ix_vl_schedule_due", _schedules.c.active, _schedules.c.next_run)
HANDLERS: dict[str, Callable] = {}
BACKOFF = (30, 120, 600, 1800, 7200, 21600)

def ensure():
    from .db import extra_tables; extra_tables.ensure(_meta)

def _manager():
    session = get_session()
    if session.user != "Administrator" and "System Manager" not in session.roles:
        raise PermissionDenied("System Manager permission is required")

def register_handler(name: str, handler: Callable, *, roles=()):
    """Register an app-owned callable under a stable name, e.g. 'my_app.jobs.rebuild'."""
    if not isinstance(name, str) or not name or len(name) > 240 or not callable(handler):
        raise ValueError("A handler name and callable are required")
    if isinstance(roles, str) or not all(isinstance(r, str) and r for r in roles):
        raise ValueError("Handler roles must be an iterable of non-empty role names")
    HANDLERS[name] = handler
    handler.velora_service_roles = frozenset(roles)

def _resolve(name: str):
    if name in HANDLERS:
        return HANDLERS[name]
    from .meta.registry import registry
    declared = registry.job_handlers()
    path = declared.get(name)
    if not path:
        raise ValidationError(f"Job handler {name!r} is not registered by an installed app")
    module, sep, attr = path.rpartition(".")
    if not sep or not module or not attr:
        raise ValidationError(f"Invalid registered job handler path: {path}")
    fn = getattr(importlib.import_module(module), attr)
    if not callable(fn):
        raise ValidationError(f"Registered job handler is not callable: {name}")
    return fn

def enqueue_job(*args, **kwargs) -> dict:
    """Queue a background job on behalf of an administrator (what the /api/jobs route calls): System Manager only."""
    _manager()
    return _enqueue(*args, **kwargs)


def enqueue_system_job(*args, **kwargs) -> dict:
    """Queue a job from TRUSTED engine code (workflow activities, SLA escalations, automation rules) while an ordinary user is signed in, for example an approver pressing Approve.
    Only the System Manager gate is skipped: the handler must still be one an installed app registered, and the payload, priority and retries are validated exactly the same.
    It is not reachable over the API, and the job records who triggered it."""
    return _enqueue(*args, **kwargs)


def _enqueue(handler: str, payload: dict | None = None, *, priority: int = 5,
             run_at: datetime | None = None, max_attempts: int = 5,
             idempotency_key: str | None = None, depends_on: list[str] | None = None) -> dict:
    ensure()
    if not isinstance(handler, str) or not handler or len(handler) > 240:
        raise ValidationError("A registered handler name is required")
    _resolve(handler)  # validate the installed-app allow-list before persisting the job
    if not isinstance(payload or {}, dict):
        raise ValidationError("Job payload must be an object")
    try:
        json.dumps(payload or {})
    except (TypeError, ValueError):
        raise ValidationError("Job payload must contain JSON-compatible values") from None
    if not isinstance(priority, int) or not 1 <= priority <= 10:
        raise ValidationError("Priority must be between 1 (highest) and 10 (lowest)")
    if not isinstance(max_attempts, int) or not 1 <= max_attempts <= 20:
        raise ValidationError("Maximum attempts must be between 1 and 20")
    deps = list(dict.fromkeys(depends_on or []))
    if len(deps) > 50 or any(not isinstance(x, str) or len(x) > 32 for x in deps):
        raise ValidationError("Dependencies must contain at most 50 job IDs")
    if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 180):
        raise ValidationError("Idempotency key must contain 1–180 characters")
    ident = secrets.token_hex(16)
    at = now()
    row = dict(id=ident, handler=handler, payload=payload or {}, status="Queued", priority=priority,
        run_at=run_at or at, attempts=0, max_attempts=max_attempts, depends_on=deps,
        idempotency_key=idempotency_key, created_by=get_session().user, created_on=at)
    with db.transaction() as c:
        if deps:
            found = c.execute(select(_jobs.c.id).where(_jobs.c.id.in_(deps))).scalars().all()
            if set(found) != set(deps):
                raise ValidationError("One or more dependency jobs do not exist in this company")
        if idempotency_key:
            existing = c.execute(select(_jobs).where(_jobs.c.idempotency_key == idempotency_key)).mappings().first()
            if existing:
                return dict(existing)
        c.execute(_jobs.insert().values(**row))
    return row

def create_schedule(label: str, handler: str, payload: dict, interval_seconds: int,
                    first_run: datetime | None = None) -> dict:
    _manager(); ensure()
    if not isinstance(label, str) or not label.strip() or len(label) > 160:
        raise ValidationError("Schedule label is required (maximum 160 characters)")
    if not isinstance(interval_seconds, int) or not 60 <= interval_seconds <= 31536000:
        raise ValidationError("Recurring interval must be between 60 seconds and 365 days")
    if not isinstance(payload or {}, dict):
        raise ValidationError("Schedule payload must be an object")
    try:
        json.dumps(payload or {})
    except (TypeError, ValueError):
        raise ValidationError("Schedule payload must contain JSON-compatible values") from None
    _resolve(handler)  # fail early if app did not install/register its handler
    row = dict(id=secrets.token_hex(16), label=label.strip(), handler=handler, payload=payload or {},
        interval_seconds=interval_seconds, next_run=first_run or now(), active=1,
        created_by=get_session().user, created_on=now())
    with db.transaction() as c: c.execute(_schedules.insert().values(**row))
    return row

def list_schedules() -> list[dict]:
    _manager(); ensure()
    with db.transaction() as c:
        rows = c.execute(select(_schedules).order_by(_schedules.c.next_run)).mappings().all()
    return [dict(x) for x in rows]

def set_schedule_active(schedule_id: str, active: bool) -> bool:
    _manager(); ensure()
    with db.transaction() as c:
        return c.execute(update(_schedules).where(_schedules.c.id == schedule_id)
            .values(active=1 if active else 0)).rowcount == 1

def list_jobs(status: str | None = None, limit: int = 100) -> list[dict]:
    _manager(); ensure()
    q = select(_jobs).order_by(_jobs.c.created_on.desc()).limit(min(max(int(limit), 1), 500))
    if status: q = q.where(_jobs.c.status == status)
    with db.transaction() as c: rows = c.execute(q).mappings().all()
    return [dict(x) for x in rows]

def retry_job(job_id: str) -> bool:
    _manager(); ensure()
    with db.transaction() as c:
        return c.execute(update(_jobs).where(_jobs.c.id == job_id, _jobs.c.status.in_(["Dead", "Blocked"]))
            .values(status="Queued", attempts=0, run_at=now(), claimed_by=None, claimed_at=None,
                    started_on=None, completed_on=None, last_error=None)).rowcount == 1

def cancel_job(job_id: str) -> bool:
    _manager(); ensure()
    with db.transaction() as c:
        return c.execute(update(_jobs).where(_jobs.c.id == job_id, _jobs.c.status.in_(["Queued", "Retry"]))
            .values(status="Cancelled", completed_on=now())).rowcount == 1

def recover_stuck_jobs(at: datetime | None = None) -> int:
    ensure(); at = at or now(); cutoff = at - timedelta(minutes=15)
    with db.transaction() as c:
        exhausted = c.execute(update(_jobs).where(_jobs.c.status == "Running", _jobs.c.claimed_at <= cutoff,
            _jobs.c.attempts >= _jobs.c.max_attempts).values(status="Dead", claimed_by=None, claimed_at=None,
            completed_on=at, last_error="Worker lease expired after maximum attempts")).rowcount
        retry = c.execute(update(_jobs).where(_jobs.c.status == "Running", _jobs.c.claimed_at <= cutoff)
            .values(status="Retry", run_at=at, claimed_by=None, claimed_at=None,
                    last_error="Worker lease expired; job returned to queue")).rowcount
    return exhausted + retry

def enqueue_due_schedules(at: datetime | None = None) -> int:
    ensure(); at = at or now(); count = 0
    with db.transaction() as c:
        due = c.execute(select(_schedules).where(_schedules.c.active == 1, _schedules.c.next_run <= at)
                        .order_by(_schedules.c.next_run).limit(100)).mappings().all()
        for schedule in due:
            s = dict(schedule)
            # Compare-and-set the due time first. Only the worker that advances it
            # creates the occurrence, preventing duplicate schedule jobs.
            elapsed = max(0, int((at - s["next_run"]).total_seconds()))
            steps = elapsed // s["interval_seconds"] + 1
            advanced = c.execute(update(_schedules).where(_schedules.c.id == s["id"],
                _schedules.c.active == 1, _schedules.c.next_run == s["next_run"])
                .values(next_run=s["next_run"] + timedelta(seconds=steps * s["interval_seconds"]))).rowcount
            if not advanced:
                continue
            c.execute(_jobs.insert().values(id=secrets.token_hex(16), handler=s["handler"], payload=s["payload"],
                status="Queued", priority=5, run_at=at, attempts=0, max_attempts=5, depends_on=[],
                idempotency_key=None, created_by="Scheduler", created_on=at))
            count += 1
    return count

def process_due_jobs(limit: int = 20, owner: str = "worker") -> dict:
    ensure(); stats = {"completed": 0, "retry": 0, "dead": 0, "blocked": 0}
    at = now()
    enqueue_due_schedules(at)
    recover_stuck_jobs(at)
    with db.transaction() as c:
        candidates = c.execute(select(_jobs).where(_jobs.c.status.in_(["Queued", "Retry"]),
            _jobs.c.run_at <= at).order_by(_jobs.c.priority, _jobs.c.created_on).limit(min(max(limit, 1), 100))).mappings().all()
    for candidate in candidates:
        job = dict(candidate)
        with db.transaction() as c:
            # Dependencies must all be completed. A failed/cancelled dependency blocks this job.
            if job["depends_on"]:
                deps = c.execute(select(_jobs.c.id, _jobs.c.status).where(_jobs.c.id.in_(job["depends_on"]))).all()
                states = {x.id: x.status for x in deps}
                if any(states.get(d) in ("Dead", "Cancelled", "Blocked") for d in job["depends_on"]):
                    c.execute(update(_jobs).where(_jobs.c.id == job["id"], _jobs.c.status.in_(["Queued", "Retry"]))
                        .values(status="Blocked", completed_on=at, last_error="A dependency did not complete"))
                    stats["blocked"] += 1
                    continue
                if any(states.get(d) != "Completed" for d in job["depends_on"]):
                    continue
            claimed = c.execute(update(_jobs).where(_jobs.c.id == job["id"], _jobs.c.status.in_(["Queued", "Retry"]))
                .values(status="Running", attempts=_jobs.c.attempts + 1, claimed_by=owner, claimed_at=at,
                        started_on=at)).rowcount
        if not claimed: continue
        attempt = job["attempts"] + 1
        try:
            fn = _resolve(job["handler"])
            # Never execute application work as Administrator merely because the
            # worker process has a privileged default session. Handlers receive a
            # named service principal and only explicitly declared service roles.
            service = Session(
                user=f"service:{job['handler']}",
                roles=frozenset(getattr(fn, "velora_service_roles", ())),
                attributes={"service_account": True, "job_id": job["id"],
                            "created_by": job["created_by"], "company_local": True},
            )
            with session_as(service):
                if getattr(fn, "manages_transactions", False):
                    result = fn(job["payload"])
                else:
                    with db.transaction():
                        result = fn(job["payload"])
            safe_result = json.loads(json.dumps(result, default=str)) if result is not None else None
            with db.transaction() as c:
                c.execute(update(_jobs).where(_jobs.c.id == job["id"], _jobs.c.status == "Running")
                    .values(status="Completed", completed_on=now(), claimed_by=None, claimed_at=None,
                            result=safe_result, last_error=None))
            stats["completed"] += 1
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}"[:4000]
            dead = attempt >= job["max_attempts"]
            delay = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            with db.transaction() as c:
                c.execute(update(_jobs).where(_jobs.c.id == job["id"], _jobs.c.status == "Running")
                    .values(status="Dead" if dead else "Retry", run_at=now() + timedelta(seconds=delay),
                            claimed_by=None, claimed_at=None, completed_on=now() if dead else None, last_error=error))
            stats["dead" if dead else "retry"] += 1
    return stats
