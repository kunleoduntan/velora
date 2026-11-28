"""The outbox: delivers queued notifications with retries.

A delivery is CLAIMED with one atomic UPDATE (so any number of workers share the queue), sent OUTSIDE any database transaction, and its outcome committed
immediately. Failures back off 1 min, 5 min, 30 min, 2 h, 12 h and then become Dead (visible, retryable by an administrator). A worker that dies mid-send leaves a
'Sending' row that `recover_stuck` returns to the queue. Delivery is at-least-once: the one unavoidable duplicate is a crash between a successful send and the commit.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from velora import db
from velora.db.tables import get_table
from velora.document.document import now

from . import channels
from .channels import PermanentError

BACKOFF = (60, 300, 1800, 7200, 43200)
MAX_ATTEMPTS = len(BACKOFF)
STUCK_MINUTES = 10
PRIORITY = {"Urgent": 0, "High": 1, "Normal": 2, "Low": 3}


def _t():
    return get_table("Notification Delivery")


def _claim(name: str, at: datetime) -> bool:
    t = _t()
    with db.transaction() as c:
        return c.execute(update(t).where(t.c.name == name, t.c.status == "Queued").values(status="Sending", claimed_at=at)).rowcount == 1


def _row(name: str) -> dict:
    t = _t()
    with db.transaction() as c:
        return dict(c.execute(select(t).where(t.c.name == name)).mappings().one())


def _finish(name: str, **vals) -> None:
    t = _t()
    with db.transaction() as c:
        c.execute(update(t).where(t.c.name == name).values(**vals))


def process_due(at: datetime | None = None, limit: int = 50) -> dict:
    at = at or now()
    t = _t()
    with db.transaction() as c:
        due = c.execute(select(t.c.name, t.c.priority).where(t.c.status == "Queued", t.c.next_attempt <= at).order_by(t.c.next_attempt).limit(limit)).all()
    stats = {"sent": 0, "retry": 0, "dead": 0, "taken_by_another_worker": 0}
    cfg = channels.settings()
    for name, _p in sorted(due, key=lambda r: PRIORITY.get(r[1], 2)):                      # urgent first
        if not _claim(name, at):
            stats["taken_by_another_worker"] += 1
            continue
        row = _row(name)
        sender = channels.CHANNELS.get(row["channel"])
        try:
            if sender is None:
                raise PermanentError(f"No sender is registered for {row['channel']}")
            sender(row, cfg)                                                               # network I/O: no transaction is open here
            _finish(name, status="Sent", sent_on=at, last_error=None)
            stats["sent"] += 1
        except PermanentError as e:
            _finish(name, status="Dead", last_error=str(e)[:500], attempts=(row["attempts"] or 0) + 1)
            stats["dead"] += 1
        except Exception as e:  # noqa: BLE001 - anything else is treated as temporary
            n = (row["attempts"] or 0) + 1
            if n >= MAX_ATTEMPTS:
                _finish(name, status="Dead", last_error=f"gave up after {n} attempts: {type(e).__name__}: {e}"[:500], attempts=n)
                stats["dead"] += 1
            else:
                _finish(name, status="Queued", attempts=n, next_attempt=at + timedelta(seconds=BACKOFF[n - 1]), last_error=f"{type(e).__name__}: {e}"[:500])
                stats["retry"] += 1
    return stats


def recover_stuck(at: datetime | None = None) -> int:
    """A worker that died mid-send leaves a 'Sending' row; put it back (counting the lost attempt)."""
    at = at or now()
    t = _t()
    cutoff = at - timedelta(minutes=STUCK_MINUTES)
    with db.transaction() as c:
        dead = c.execute(update(t).where(t.c.status == "Sending", t.c.claimed_at <= cutoff, t.c.attempts + 1 >= MAX_ATTEMPTS).values(status="Dead", attempts=t.c.attempts + 1,
                                                                                                                                     last_error="the worker stopped while sending, too many times")).rowcount
        back = c.execute(update(t).where(t.c.status == "Sending", t.c.claimed_at <= cutoff).values(status="Queued", attempts=t.c.attempts + 1, next_attempt=at,
                                                                                                   last_error="the worker stopped while sending; trying again")).rowcount
    return dead + back


def release_digests(at: datetime | None = None) -> int:
    """Held deliveries whose time has come: one combined message per recipient (a single one is released as it is)."""
    at = at or now()
    t = _t()
    with db.transaction() as c:
        held = [dict(r) for r in c.execute(select(t).where(t.c.status == "Held", t.c.next_attempt <= at).order_by(t.c.recipient, t.c.creation)).mappings()]
    groups: dict[tuple, list[dict]] = {}
    for h in held:
        groups.setdefault((h["recipient"], h["channel"]), []).append(h)
    sent = 0
    for (rcpt, ch), items in groups.items():
        with db.transaction() as c:
            if len(items) == 1:
                c.execute(update(t).where(t.c.name == items[0]["name"]).values(status="Queued", next_attempt=at))
                continue
            body = "\n\n".join(f"- {i['subject']}\n  {(i['payload'] or {}).get('link', '')}".rstrip() for i in items)
            from .engine import _insert  # local: avoids an import cycle at load
            merged_key = f"digest:{rcpt}:{ch}:{at.isoformat(timespec='minutes')}"
            if _insert("Notification Delivery", dict(rule="(digest)", channel=ch, recipient=rcpt, user=items[0]["user"], subject=f"{len(items)} notifications", body=body, status="Queued",
                                                     attempts=0, next_attempt=at, idempotency_key=merged_key, payload={}, priority="Normal")):
                new = c.execute(select(t.c.name).where(t.c.idempotency_key == merged_key)).scalar()
                c.execute(update(t).where(t.c.name.in_([i["name"] for i in items])).values(status="Sent", sent_on=at, last_error=f"merged into digest {new}"))
                sent += 1
    return sent


def retry(name: str) -> dict:
    t = _t()
    with db.transaction() as c:
        n = c.execute(update(t).where(t.c.name == name, t.c.status.in_(["Dead", "Skipped"])).values(status="Queued", attempts=0, next_attempt=now(), last_error=None)).rowcount
    if not n:
        raise ValueError("Only a Dead or Skipped delivery can be retried")
    return _row(name)


def stats() -> dict:
    t = _t()
    with db.transaction() as c:
        return {s: n for s, n in c.execute(select(t.c.status, func.count()).group_by(t.c.status)).all()}
