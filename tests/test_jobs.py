from datetime import timedelta

import pytest

from velora import jobs
from velora.document.document import now
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import ADMINISTRATOR, Session, session_as

CALLS = []

def _record(payload):
    CALLS.append(payload)
    return {"received": payload.get("value")}

jobs.register_handler("tests.test_jobs._record", _record)

def test_enqueue_and_execute_job(site):
    CALLS.clear()
    queued = jobs.enqueue_job("tests.test_jobs._record", {"value": 12})
    stats = jobs.process_due_jobs()
    assert stats["completed"] == 1
    assert CALLS == [{"value": 12}]
    row = jobs.list_jobs()[0]
    assert row["id"] == queued["id"] and row["status"] == "Completed"
    assert row["result"] == {"received": 12}

def test_idempotency_key_returns_existing_job(site):
    first = jobs.enqueue_job("tests.test_jobs._record", {"value": 1}, idempotency_key="once-only")
    second = jobs.enqueue_job("tests.test_jobs._record", {"value": 2}, idempotency_key="once-only")
    assert first["id"] == second["id"]
    assert second["payload"] == {"value": 1}

def test_priority_and_dependency_order(site):
    CALLS.clear()
    first = jobs.enqueue_job("tests.test_jobs._record", {"value": "first"}, priority=10)
    dependent = jobs.enqueue_job("tests.test_jobs._record", {"value": "dependent"},
                                 priority=1, depends_on=[first["id"]])
    independent = jobs.enqueue_job("tests.test_jobs._record", {"value": "urgent"}, priority=1)
    jobs.process_due_jobs(limit=10)
    jobs.process_due_jobs(limit=10)
    assert CALLS == [{"value": "urgent"}, {"value": "first"}, {"value": "dependent"}]

def test_retry_and_dead_letter(site, monkeypatch):
    attempts = []
    def fail(payload):
        attempts.append(1)
        raise RuntimeError("temporary failure")
    jobs.register_handler("tests.test_jobs._fail", fail)
    row = jobs.enqueue_job("tests.test_jobs._fail", {}, max_attempts=1)
    result = jobs.process_due_jobs()
    assert result["dead"] == 1
    assert jobs.retry_job(row["id"])
    with jobs.db.transaction() as c:
        current = c.execute(jobs._jobs.select().where(jobs._jobs.c.id == row["id"])).mappings().one()
    assert current["status"] == "Queued" and current["attempts"] == 0

def test_recurring_schedule_creates_one_job_and_advances(site):
    with session_as(ADMINISTRATOR):
        schedule = jobs.create_schedule("Hourly report", "tests.test_jobs._record", {}, 3600, now()-timedelta(seconds=10))
        assert schedule["active"] == 1
    assert jobs.enqueue_due_schedules() == 1
    with jobs.db.transaction() as c:
        row = c.execute(jobs._schedules.select().where(jobs._schedules.c.id == schedule["id"])).mappings().one()
        queued = c.execute(jobs._jobs.select().where(jobs._jobs.c.handler == "tests.test_jobs._record")).mappings().all()
    assert row["next_run"] > now()
    assert len(queued) == 1

def test_job_payload_and_schedule_limits(site):
    with pytest.raises(ValidationError):
        jobs.enqueue_job("tests.test_jobs._record", object())
    with session_as(ADMINISTRATOR):
        with pytest.raises(ValidationError):
            jobs.create_schedule("Too fast", "tests.test_jobs._record", {}, 5)

def test_job_management_requires_system_manager(site):
    with session_as(Session("staff", frozenset({"Sales User"}))):
        with pytest.raises(PermissionDenied):
            jobs.list_jobs()


def test_job_api_requires_auth_and_allows_manager(site):
    from fastapi.testclient import TestClient
    from velora.api import create_app
    client = TestClient(create_app(auto_init=False))
    assert client.get("/api/jobs").status_code == 401
    headers = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
    response = client.post("/api/jobs", json={"handler": "tests.test_jobs._record",
        "payload": {"value": "api"}, "priority": 2}, headers=headers)
    assert response.status_code == 200
    job = response.json()["data"]
    assert job["status"] == "Queued"
    assert client.get("/api/jobs", headers=headers).status_code == 200


def test_unregistered_handler_is_rejected(site):
    with pytest.raises(ValidationError, match="not registered"):
        jobs.enqueue_job("os.system", {"command": "unsafe"})


def test_failed_dependency_blocks_child_and_admin_can_retry(site):
    def fail(payload):
        raise RuntimeError("permanent")
    jobs.register_handler("tests.test_jobs._parent", fail)
    child_calls = []
    jobs.register_handler("tests.test_jobs._child", lambda payload: child_calls.append(payload) or {"ok": True})
    parent = jobs.enqueue_job("tests.test_jobs._parent", {}, max_attempts=1)
    child = jobs.enqueue_job("tests.test_jobs._child", {"child": True}, depends_on=[parent["id"]])
    result = jobs.process_due_jobs(limit=10)
    assert result["dead"] == 1 and result["blocked"] == 1
    with jobs.db.transaction() as c:
        child_row = c.execute(jobs._jobs.select().where(jobs._jobs.c.id == child["id"])).mappings().one()
    assert child_row["status"] == "Blocked"
    jobs.register_handler("tests.test_jobs._parent", lambda payload: {"ok": True})
    assert jobs.retry_job(parent["id"])
    jobs.process_due_jobs(limit=10)
    assert jobs.retry_job(child["id"])
    jobs.process_due_jobs(limit=10)
    assert child_calls == [{"child": True}]


def test_stale_job_lease_is_recovered(site):
    row = jobs.enqueue_job("tests.test_jobs._record", {"value": "lease"})
    with jobs.db.transaction() as c:
        c.execute(jobs._jobs.update().where(jobs._jobs.c.id == row["id"]).values(
            status="Running", attempts=1, claimed_at=now()-timedelta(minutes=20), claimed_by="crashed-worker"))
    assert jobs.recover_stuck_jobs() == 1
    with jobs.db.transaction() as c:
        recovered = c.execute(jobs._jobs.select().where(jobs._jobs.c.id == row["id"])).mappings().one()
    assert recovered["status"] == "Retry" and recovered["claimed_at"] is None


# ---- trusted engines may queue jobs for an ordinary user, and nobody else gets that for free ----
APPROVER = Session("approver@example.com", frozenset({"Approver", "Sales User"}))


def test_the_public_queue_is_still_for_system_managers_only(site):
    with session_as(APPROVER):
        with pytest.raises(PermissionDenied, match="System Manager"):
            jobs.enqueue_job("tests.test_jobs._record", {"value": 1})
    assert jobs.enqueue_job("tests.test_jobs._record", {"value": 1})["status"] == "Queued"                 # an administrator still can


def test_engine_code_can_queue_a_registered_handler_while_an_ordinary_user_is_signed_in(site):
    CALLS.clear()
    with session_as(APPROVER):
        queued = jobs.enqueue_system_job("tests.test_jobs._record", {"value": 7}, idempotency_key="wf:1")
    assert queued["created_by"] == "approver@example.com"                                                   # the job records who triggered it
    assert jobs.process_due_jobs()["completed"] == 1 and CALLS == [{"value": 7}]


def test_the_trusted_path_skips_only_the_role_gate_never_the_handler_allow_list_or_validation(site):
    with session_as(APPROVER):
        with pytest.raises(ValidationError, match="not registered"):
            jobs.enqueue_system_job("os.system", {"value": 1})                                              # an arbitrary callable can never be queued
        with pytest.raises(ValidationError, match="not registered"):
            jobs.enqueue_system_job("tests.test_jobs.not_registered", {})
        with pytest.raises(ValidationError, match="JSON-compatible"):
            jobs.enqueue_system_job("tests.test_jobs._record", {"x": object()})
        with pytest.raises(ValidationError, match="Priority"):
            jobs.enqueue_system_job("tests.test_jobs._record", {}, priority=99)
        with pytest.raises(ValidationError, match="Maximum attempts"):
            jobs.enqueue_system_job("tests.test_jobs._record", {}, max_attempts=0)
        with pytest.raises(ValidationError, match="Idempotency"):
            jobs.enqueue_system_job("tests.test_jobs._record", {}, idempotency_key="x" * 200)


def test_the_http_api_never_offers_the_trusted_path(site):
    import inspect
    from velora.api import jobs as api_jobs
    src = inspect.getsource(api_jobs)
    assert "enqueue_system_job" not in src and "jobs.enqueue_job(" in src                                   # the route keeps the gated, administrator-only function
