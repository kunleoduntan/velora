"""Database access: one transaction per unit of work, on the current site's engine.

`transaction()` joins an existing transaction when nested, so a document save
triggered from inside another document's hook shares the same atomic unit.
"""
import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from .. import site as _site

_conn: ContextVar[Connection | None] = ContextVar("velora_conn", default=None)
_after_commit: ContextVar[list | None] = ContextVar("velora_after_commit", default=None)
_after_rollback: ContextVar[list | None] = ContextVar("velora_after_rollback", default=None)
log = logging.getLogger("velora.db")
_sqlite_locks: dict[int, threading.RLock] = {}
_sqlite_locks_guard = threading.Lock()


def get_engine() -> Engine:
    return _site.current().engine


@contextmanager
def transaction():
    existing = _conn.get()
    if existing is not None:
        yield existing
        return
    pending_commit: list = []
    pending_rollback: list = []
    engine = get_engine()
    lock = None
    if engine.dialect.name == "sqlite":
        # SQLite permits one writer per database. Serialise transaction scopes per
        # company database in-process instead of surfacing SQLITE_BUSY under load.
        key = id(engine)
        with _sqlite_locks_guard:
            lock = _sqlite_locks.setdefault(key, threading.RLock())
        lock.acquire()
    try:
        with engine.begin() as conn:
            token = _conn.set(conn)
            cb_token = _after_commit.set(pending_commit)
            rb_token = _after_rollback.set(pending_rollback)
            try:
                yield conn
            finally:
                _conn.reset(token)
                _after_commit.reset(cb_token)
                _after_rollback.reset(rb_token)
    except Exception:
        for fn in pending_rollback:
            try:
                fn()
            except Exception:
                log.exception("after-rollback cleanup failed")
        raise
    else:
        for fn in pending_commit:
            try:
                fn()
            except Exception:  # noqa: BLE001 - data is committed; cleanup failure is logged
                log.exception("after-commit callback failed")
    finally:
        if lock is not None:
            lock.release()

def on_commit(fn) -> None:
    """Run `fn()` once the current transaction has COMMITTED (never if it rolls back); immediately when there is no transaction."""
    pending = _after_commit.get()
    if pending is None or _conn.get() is None:
        fn()
    else:
        pending.append(fn)


def conn() -> Connection:
    c = _conn.get()
    if c is None:
        raise RuntimeError("No active transaction; wrap the call in db.transaction()")
    return c


def exists(doctype: str, name: str) -> bool:
    from .tables import get_table

    t = get_table(doctype)
    with transaction() as c:
        return c.execute(select(t.c.name).where(t.c.name == name)).first() is not None


def on_rollback(fn) -> None:
    """Run cleanup if the outermost transaction rolls back."""
    pending = _after_rollback.get()
    if pending is not None and _conn.get() is not None:
        pending.append(fn)
