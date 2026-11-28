"""Live events: after-commit hook, the hub, the PostgreSQL LISTEN/NOTIFY listener, and the /api/events stream (against a real server)."""
import asyncio
import queue
import threading
import time

import httpx
import pytest
import uvicorn

from velora import db, new_doc, realtime
from velora.api import create_app
from velora.db import get_engine
from velora.realtime import HUB, Hub

from test_notify import ADMIN, ALICE, BOLA, customer, rule, ns  # noqa: F401


def on_pg():
    return get_engine().dialect.name == "postgresql"


@pytest.fixture(autouse=True)
def clean_hub():
    """The hub is process-wide: every test starts and ends with no subscribers and no listener threads."""
    HUB.reset()
    yield
    HUB.reset()
    for t in [t for t in threading.enumerate() if t.name.startswith("velora-listen")]:
        t.join(timeout=5)


# ============================== db.on_commit ==============================
def test_after_commit_callbacks_run_only_after_a_commit(ns):
    seen = []
    with db.transaction():
        db.on_commit(lambda: seen.append("a"))
        assert seen == []                                                                                              # not yet: the transaction is still open
        with db.transaction():                                                                                         # a nested call joins the same transaction ...
            db.on_commit(lambda: seen.append("b"))
    assert seen == ["a", "b"]                                                                                          # ... and its callbacks wait for the OUTER commit, in order
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.on_commit(lambda: seen.append("never"))
            raise RuntimeError("rolled back")
    assert seen == ["a", "b"]
    db.on_commit(lambda: seen.append("now"))                                                                           # no transaction: runs at once
    assert seen[-1] == "now"


def test_a_failing_after_commit_callback_does_not_undo_or_fail_the_commit(ns, caplog):
    with db.transaction():
        customer("Committed")
        db.on_commit(lambda: 1 / 0)
        db.on_commit(lambda: caplog.set_level(0))
    assert "after-commit callback failed" in caplog.text
    from velora import get_list
    assert [r["customer_name"] for r in get_list("Customer", fields=["customer_name"], ignore_permissions=True)] == ["Committed"]


# ============================== the hub ==============================
@pytest.fixture
def loop():
    lp = asyncio.new_event_loop()
    yield lp
    lp.close()


def drain(lp, sub, n=1, timeout=3.0):
    """Collect up to n messages (running the loop so cross-thread deliveries are processed)."""
    out = []

    async def go():
        for _ in range(n):
            out.append(await asyncio.wait_for(sub.queue.get(), timeout))
    try:
        lp.run_until_complete(go())
    except asyncio.TimeoutError:
        pass
    return out


def nothing(lp, sub):
    lp.run_until_complete(asyncio.sleep(0.15))
    return sub.queue.empty()


def test_the_hub_routes_by_user_and_database_and_never_forwards_content(loop):
    h = Hub()
    a, b, other = h.subscribe("db1", "Alice@acme.ng", loop), h.subscribe("db1", "bola@acme.ng", loop), h.subscribe("db2", "alice@acme.ng", loop)
    h.publish("db1", {"kind": "notification", "user": "ALICE@acme.ng", "subject": "secret salary figures", "body": "x"})
    assert drain(loop, a) == [{"kind": "notification"}]                                                                # case-insensitive match, ONLY the kind is delivered
    assert nothing(loop, b) and nothing(loop, other)                                                                   # not Bola, not another company's Alice
    h.publish("db1", {"kind": "resync"})                                                                               # no user = everyone in that database
    assert drain(loop, a) == [{"kind": "resync"}] and drain(loop, b) == [{"kind": "resync"}] and nothing(loop, other)
    assert h.count() == 3 and h.count("db1") == 2
    h.unsubscribe(a); h.unsubscribe(b); h.unsubscribe(other)
    assert h.count() == 0
    h.publish("db1", {"kind": "notification", "user": "alice@acme.ng"})                                                # nobody listening: harmless


def test_limits_protect_the_server(loop, monkeypatch):
    h = Hub()
    monkeypatch.setattr(realtime, "MAX_PER_USER", 2)
    s1, s2 = h.subscribe("d", "a@x.co", loop), h.subscribe("d", "a@x.co", loop)
    with pytest.raises(OverflowError, match="at most 2 live connections per user"):
        h.subscribe("d", "a@x.co", loop)
    h.subscribe("d", "b@x.co", loop)                                                                                   # other users are unaffected
    h.unsubscribe(s1)
    h.subscribe("d", "a@x.co", loop)                                                                                   # a slot was freed
    monkeypatch.setattr(realtime, "MAX_TOTAL", 3)
    with pytest.raises(OverflowError, match="too many live connections"):
        h.subscribe("d", "c@x.co", loop)
    assert s2


def test_a_client_that_cannot_keep_up_gets_one_resync_not_an_unbounded_backlog(loop):
    h = Hub()
    s = h.subscribe("d", "a@x.co", loop)
    for _ in range(150):
        h.publish("d", {"kind": "notification", "user": "a@x.co"})
    loop.run_until_complete(asyncio.sleep(0.2))
    assert s.queue.qsize() <= 100 and {"kind": "resync"} in list(s.queue._queue)


def test_delivering_to_a_closed_loop_is_ignored():
    lp = asyncio.new_event_loop()
    h = Hub()
    h.subscribe("d", "a@x.co", lp)
    lp.close()
    h.publish("d", {"kind": "notification", "user": "a@x.co"})                                                         # the client's connection is gone: no error


# ============================== an event after commit; none after rollback ==============================
def listen(loop, user="alice@acme.ng"):
    with_info = realtime.describe()
    sub = HUB.subscribe(with_info["key"], user, loop, with_info["dsn"])
    if on_pg():
        deadline = time.time() + 5
        while not HUB._listeners[with_info["key"]].connected.is_set() and time.time() < deadline:
            time.sleep(0.02)
    return sub


def test_creating_a_notification_pushes_an_event_only_once_it_has_committed(ns, loop):
    rule("live", recipients=(("User", "alice@acme.ng"),), channels=("In-App",))
    sub = listen(loop)
    try:
        with pytest.raises(RuntimeError):
            with db.transaction():
                customer("Rolled back")
                raise RuntimeError("no")
        assert nothing(loop, sub)                                                                                       # a notification that never existed sends no event
        customer("Committed")
        assert drain(loop, sub) == [{"kind": "notification"}]
        rule("other", recipients=(("User", "bola@acme.ng"),), channels=("In-App",))
        customer("For bola too")
        assert drain(loop, sub, 1) == [{"kind": "notification"}] and nothing(loop, sub)                                # alice gets hers; bola's rule does not wake alice
    finally:
        HUB.unsubscribe(sub)


def test_the_listener_reconnects_after_losing_its_connection_and_asks_everyone_to_resync(ns, loop):
    if not on_pg():
        pytest.skip("PostgreSQL only")
    rule("live", recipients=(("User", "alice@acme.ng"),), channels=("In-App",))
    sub = listen(loop)
    try:
        with db.transaction() as c:
            killed = c.exec_driver_sql("select count(*) from (select pg_terminate_backend(pid) from pg_stat_activity where query like 'LISTEN velora_events%%') t").scalar()
        assert killed == 1
        assert drain(loop, sub, 1, timeout=8) == [{"kind": "resync"}]                                                   # it noticed, reconnected, and told clients to refetch
        customer("After the outage")
        assert drain(loop, sub) == [{"kind": "notification"}]                                                           # and live events work again
    finally:
        HUB.unsubscribe(sub)


def test_the_listener_stops_when_the_last_subscriber_leaves(ns, loop):
    if not on_pg():
        pytest.skip("PostgreSQL only")
    sub = listen(loop)
    key = sub.key
    th = HUB._listeners[key]
    HUB.unsubscribe(sub)
    th.join(timeout=5)
    assert not th.is_alive() and key not in HUB._listeners                                                              # no idle connection is kept open


# ============================== the HTTP stream, against a real server ==============================
@pytest.fixture
def server(ns):
    app = create_app(auto_init=False)
    cfg = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="on")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    deadline = time.time() + 10
    while not srv.started and time.time() < deadline:
        time.sleep(0.02)
    port = srv.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=10)


class Stream:
    """Reads an event stream in a background thread; `.lines` collects what arrives."""

    def __init__(self, url, headers):
        self.q, self.status, self.headers, self.stop = queue.Queue(), None, {}, threading.Event()
        self.t = threading.Thread(target=self.run, args=(url, headers), daemon=True)
        self.t.start()

    def run(self, url, headers):
        try:
            with httpx.stream("GET", url + "/api/events", headers=headers, timeout=20) as r:
                self.status, self.headers = r.status_code, dict(r.headers)
                if r.status_code != 200:
                    self.q.put(r.read().decode())
                    return
                for line in r.iter_lines():
                    self.q.put(line)
                    if self.stop.is_set():
                        break
        except Exception as e:  # noqa: BLE001
            self.q.put(f"ERR {type(e).__name__}")

    def wait_for(self, needle, timeout=6):
        end, got = time.time() + timeout, []
        while time.time() < end:
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            got.append(line)
            if needle in line:
                return got
        return None


def test_the_event_stream_delivers_my_events_and_nobody_elses(ns, server):
    rule("live", recipients=(("User", "alice@acme.ng"), ("User", "bola@acme.ng")), channels=("In-App",))
    a, b = Stream(server, ALICE), Stream(server, BOLA)
    try:
        assert a.wait_for("event: ready") and b.wait_for("event: ready")
        assert a.status == 200 and a.headers["content-type"].startswith("text/event-stream") and a.headers["cache-control"] == "no-cache" and a.headers["x-accel-buffering"] == "no"
        if on_pg():
            time.sleep(0.5)                                                                                              # the listener connects just after the first subscriber
        customer("Acme")
        ga, gb = a.wait_for("event: notification"), b.wait_for("event: notification")
        assert ga and gb and not any("Acme" in x or "subject" in x for x in ga + gb)                                     # the event carries no content
        # now a rule that notifies ONLY Alice, on Save
        rule("only-alice", recipients=(("User", "alice@acme.ng"),), channels=("In-App",), subject="solo", event="Save")
        c = customer("Solo")
        assert a.wait_for("event: notification") and b.wait_for("event: notification")                                   # (the New rule notifies both)
        c.credit_limit = 5
        c.save()
        assert a.wait_for("event: notification")
        assert b.wait_for("event: notification", timeout=1.5) is None                                                    # Bola's stream stays silent for Alice's notification
    finally:
        a.stop.set(); b.stop.set()


def test_marking_read_updates_my_other_tabs(ns, server):
    rule("live", recipients=(("User", "alice@acme.ng"),), channels=("In-App",))
    customer("One")
    from fastapi.testclient import TestClient
    tab2 = Stream(server, ALICE)
    try:
        assert tab2.wait_for("event: ready")
        if on_pg():
            time.sleep(0.5)
        c = TestClient(create_app(auto_init=False))
        assert c.post("/api/notifications/read-all", headers=ALICE).json()["data"]["marked"] == 1
        assert tab2.wait_for("event: read")                                                                              # the other tab learns the count changed
    finally:
        tab2.stop.set()


def test_the_stream_requires_sign_in_is_limited_per_user_and_says_when_not_installed(ns, server, monkeypatch):
    s = Stream(server, {})
    s.t.join(timeout=5)
    assert s.status == 401
    monkeypatch.setattr(realtime, "MAX_PER_USER", 1)
    first = Stream(server, ALICE)
    try:
        assert first.wait_for("event: ready")
        second = Stream(server, ALICE)
        time.sleep(1.0)
        assert second.status == 429 and any("at most 1 live connections per user" in x for x in list(second.q.queue))
        other = Stream(server, BOLA)
        assert other.wait_for("event: ready")                                                                            # another user is unaffected
        other.stop.set()
    finally:
        first.stop.set()


def test_closing_the_stream_frees_the_subscription(ns, server):
    s = Stream(server, ALICE)
    assert s.wait_for("event: ready")
    assert HUB.count() == 1
    s.stop.set()
    rule("live", recipients=(("User", "alice@acme.ng"),), channels=("In-App",))
    customer("wake the reader so it notices it should stop")
    deadline = time.time() + 20
    while HUB.count() and time.time() < deadline:
        time.sleep(0.2)
    assert HUB.count() == 0
