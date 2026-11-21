"""Live events (the notification bell updates the instant something happens) without polling.

PostgreSQL: `pg_notify` inside the transaction (delivered ONLY if it commits), and ONE listener thread per database that holds a `LISTEN` connection and fans the
events out to whoever has an event stream open. Every server process listens for itself, so it works across several processes/machines with no broker.
Other databases (SQLite, development): the same events go through an in-process hub after the commit.

Events carry only {kind, user} - never the content. The client reacts by asking the normal API, which applies the normal permissions.
A listener that loses its connection reconnects and tells everyone to resync (events during the gap cannot be replayed).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field

from . import db
from . import site as site_mod
from .company import current_company
from .permissions import get_session

log = logging.getLogger("velora.realtime")
CHANNEL = "velora_events"
MAX_PER_USER, MAX_TOTAL = 5, 2000


def site_key() -> str:
    c = current_company()
    return f"c:{c.id}" if c else "s:" + site_mod.current().engine.url.render_as_string(hide_password=True)


def describe() -> dict:
    """Inside a request scope: who is listening, to which database."""
    eng = site_mod.current().engine
    dsn = eng.url.set(drivername="postgresql").render_as_string(hide_password=False) if eng.dialect.name == "postgresql" else None
    return {"user": get_session().user, "key": site_key(), "dsn": dsn}


def notify(user: str | None, kind: str = "notification") -> None:
    """Tell `user`'s open sessions that something changed (the transaction must commit first; a rollback sends nothing). Never raises."""
    try:
        payload = {"kind": kind, "user": (user or "").lower() or None}
        eng = site_mod.current().engine
        if eng.dialect.name == "postgresql":
            db.conn().exec_driver_sql("SELECT pg_notify(%s, %s)", (CHANNEL, json.dumps(payload)))
        else:
            key = site_key()
            db.on_commit(lambda: HUB.publish(key, payload))
    except Exception:  # noqa: BLE001 - a missing live update must never break the save that caused it
        log.exception("realtime notify failed")


@dataclass(eq=False)
class Subscriber:
    key: str
    user: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=100))

    def _put(self, msg: dict) -> None:
        if self.queue.full():                                    # a client that cannot keep up gets one "resync" instead of an unbounded backlog
            while not self.queue.empty():
                self.queue.get_nowait()
            msg = {"kind": "resync"}
        self.queue.put_nowait(msg)

    def deliver(self, msg: dict) -> None:
        try:
            self.loop.call_soon_threadsafe(self._put, msg)
        except RuntimeError:                                     # the loop is closed: the client is gone
            pass


class Listener(threading.Thread):
    """One per PostgreSQL database that has subscribers."""

    def __init__(self, key: str, dsn: str, hub: "Hub"):
        super().__init__(daemon=True, name=f"velora-listen-{key}")
        self.key, self.dsn, self.hub, self.stop_flag, self.connected = key, dsn, hub, threading.Event(), threading.Event()

    def run(self) -> None:
        import psycopg
        backoff, first = 1.0, True
        while not self.stop_flag.is_set():
            try:
                with psycopg.connect(self.dsn, autocommit=True, connect_timeout=5) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    self.connected.set()
                    if not first:
                        self.hub.publish(self.key, {"kind": "resync"})        # we were away: anything may have happened
                    first, backoff = False, 1.0
                    while not self.stop_flag.is_set():
                        for n in conn.notifies(timeout=1.0):
                            try:
                                self.hub.publish(self.key, json.loads(n.payload))
                            except ValueError:
                                pass
            except Exception as e:  # noqa: BLE001 - lost the connection: wait, reconnect
                self.connected.clear()
                if self.stop_flag.is_set():
                    break
                log.warning("realtime listener for %s lost its connection (%s); retrying in %.0fs", self.key, type(e).__name__, backoff)
                self.stop_flag.wait(backoff)
                backoff = min(backoff * 2, 30.0)


class Hub:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs: dict[str, set[Subscriber]] = {}
        self._listeners: dict[str, Listener] = {}

    def subscribe(self, key: str, user: str, loop: asyncio.AbstractEventLoop, dsn: str | None = None) -> Subscriber:
        user = (user or "").lower()
        with self._lock:
            subs = self._subs.setdefault(key, set())
            if sum(len(v) for v in self._subs.values()) >= MAX_TOTAL:
                raise OverflowError("too many live connections on this server")
            if sum(1 for s in subs if s.user == user) >= MAX_PER_USER:
                raise OverflowError(f"at most {MAX_PER_USER} live connections per user")
            sub = Subscriber(key, user, loop)
            subs.add(sub)
            if dsn and key not in self._listeners:
                self._listeners[key] = Listener(key, dsn, self)
                self._listeners[key].start()
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        stop = None
        with self._lock:
            subs = self._subs.get(sub.key, set())
            subs.discard(sub)
            if not subs:
                self._subs.pop(sub.key, None)
                stop = self._listeners.pop(sub.key, None)
        if stop:
            stop.stop_flag.set()

    def publish(self, key: str, msg: dict) -> None:
        target = (msg.get("user") or "").lower() or None
        with self._lock:
            subs = list(self._subs.get(key, ()))
        for s in subs:
            if target is None or s.user == target:
                s.deliver({"kind": msg.get("kind", "notification")})      # only the kind: never the content

    def count(self, key: str | None = None) -> int:
        with self._lock:
            return len(self._subs.get(key, ())) if key else sum(len(v) for v in self._subs.values())

    def close(self) -> None:
        """Stop every listener (server shutdown). Subscribers are left to end with their connections."""
        with self._lock:
            ls, self._listeners = list(self._listeners.values()), {}
        for l in ls:
            l.stop_flag.set()

    def reset(self) -> None:
        """Forget everything (tests)."""
        self.close()
        with self._lock:
            self._subs.clear()


HUB = Hub()
