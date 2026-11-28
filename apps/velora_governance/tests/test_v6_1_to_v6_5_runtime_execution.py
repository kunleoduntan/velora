from datetime import date, datetime, timezone
from types import SimpleNamespace

from velora_governance.governance.services.governance_automation_scheduler import (
    collect_due_items, generate_and_persist_actions, run_queued_automation,
    dispatch_in_app_notification,
)


class CollectorAPI:
    def __init__(self, rows_by_doctype):
        self.rows_by_doctype = rows_by_doctype
        self.calls = []
    def get_list(self, doctype, **kwargs):
        self.calls.append((doctype, kwargs))
        return self.rows_by_doctype.get(doctype, [])
    def get_doc(self, *args, **kwargs):
        raise AssertionError("collector should only read list data")
    def new_doc(self, *args, **kwargs):
        raise AssertionError("collector should not create documents")


class IdempotentRepo:
    def __init__(self):
        self.records = {}
    def insert_if_absent(self, record):
        key = record["idempotency_key"]
        if key in self.records:
            return {"created": False, "record": self.records[key]}
        self.records[key] = {**record, "name": f"GAE-{len(self.records)+1}"}
        return {"created": True, "record": self.records[key]}


class RunnerRepo:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []
    def list_records(self, status=None, limit=100, offset=0):
        return self.rows[:limit]
    def update_status(self, key, status, result=None, **kwargs):
        self.updates.append((key, status, result, kwargs))
        row = next(r for r in self.rows if r["idempotency_key"] == key)
        row["status"] = status
        row["attempts"] = kwargs.get("attempts", row.get("attempts", 0))
        row["next_retry_at"] = kwargs.get("next_retry_at")
        row["result"] = result or {}
        row["error"] = kwargs.get("error")
        return row


class NotificationAPI:
    def __init__(self):
        self.created = []
    def get_list(self, doctype, filters=None, **kwargs):
        if doctype == "User":
            return [{"name": filters["name"], "enabled": 1}] if filters.get("name") == "user@example.test" else []
        if doctype == "Employee":
            return []
        if doctype == "Notification Log":
            return [{"name": f"NL-{i+1}"} for i, doc in enumerate(self.created)
                if getattr(doc, "for_user", None) == filters.get("for_user")
                and getattr(doc, "subject", None) == filters.get("subject")]
        return []
    def new_doc(self, doctype):
        doc = SimpleNamespace(doctype=doctype)
        def insert(**kw):
            doc.name = f"NL-{len(self.created)+1}"
            self.created.append(doc)
            return doc
        doc.insert = insert
        return doc


def test_collect_due_items_reads_only_allowlisted_doctypes_and_bounded_queries():
    api = CollectorAPI({"Board Action": [{"name": "BA-1", "due_date": "2026-11-26",
        "action_status": "Open", "action_title": "Approve policy", "assigned_owner": "user@example.test",
        "governance_entity": "GE-1"}]})
    items = collect_due_items(api, today=date(2026, 11, 26))
    assert items[0]["id"] == "BA-1"
    assert items[0]["owner"] == "user@example.test"
    assert items[0]["entity"] == "GE-1"
    assert all(call[1]["limit"] <= 1000 for call in api.calls)
    assert {c[0] for c in api.calls}.issubset({"Board Action", "Governance Obligation", "Corporate Filing",
        "Annual Return", "Regulatory Correspondence", "Sustainability Data Collection Task"})


def test_daily_generation_persists_idempotent_reminder_actions():
    api = CollectorAPI({"Board Action": [{"name": "BA-1", "due_date": "2026-11-26",
        "action_status": "Open", "action_title": "Approve policy", "assigned_owner": "user@example.test",
        "governance_entity": "GE-1"}]})
    repo = IdempotentRepo()
    first = generate_and_persist_actions(api=api, repository=repo, today=date(2026, 11, 26))
    second = generate_and_persist_actions(api=api, repository=repo, today=date(2026, 11, 26))
    assert first["persisted"] == 1
    assert second["duplicates"] == 1
    stored = next(iter(repo.records.values()))["action"]
    assert stored["action_type"] == "notification"
    assert stored["message"]
    assert stored["idempotency_key"]


def test_native_notification_log_dispatch_validates_user_and_creates_record():
    api = NotificationAPI()
    result = dispatch_in_app_notification({"owner": "user@example.test", "action_type": "Reminder",
        "message": "Please review", "item_type": "Board Action", "item_id": "BA-1", "idempotency_key": "1234567890abcdef"}, api=api)
    assert result["channel"] == "in_app"
    assert result["recipient"] == "user@example.test"
    assert len(api.created) == 1
    doc = api.created[0]
    assert doc.subject.startswith("Reminder [GAE-")
    assert doc.for_user == "user@example.test"
    assert doc.document_name == "BA-1"
    duplicate = dispatch_in_app_notification({"owner": "user@example.test", "action_type": "Reminder",
        "message": "Please review", "item_type": "Board Action", "item_id": "BA-1",
        "idempotency_key": "1234567890abcdef"}, api=api)
    assert duplicate["duplicate_suppressed"] is True
    assert len(api.created) == 1


def test_notification_dispatch_rejects_invalid_user():
    api = NotificationAPI()
    try:
        dispatch_in_app_notification({"owner": "not-a-user", "message": "test"}, api=api)
    except ValueError as exc:
        assert str(exc) == "recipient_not_a_valid_user"
    else:
        raise AssertionError("expected invalid recipient rejection")


def test_queued_runner_completes_notification_and_records_lifecycle():
    key = "idempotency-1"
    repo = RunnerRepo([{"name": "GAE-1", "idempotency_key": key, "status": "Queued", "attempts": 0,
        "next_retry_at": None, "action": {"action_type": "notification", "owner": "user@example.test",
        "message": "Governance reminder", "item_type": "Board Action", "item_id": "BA-1"}}])
    api = NotificationAPI()
    result = run_queued_automation(repository=repo, api=api, now=datetime(2026, 11, 26, 12, tzinfo=timezone.utc))
    assert result["completed"] == 1
    assert [u[1] for u in repo.updates] == ["Running", "Completed"]
    assert len(api.created) == 1


def test_queued_runner_failed_dispatch_sets_retry_pending_with_backoff():
    key = "idempotency-fail"
    repo = RunnerRepo([{"name": "GAE-2", "idempotency_key": key, "status": "Queued", "attempts": 0,
        "next_retry_at": None, "action": {"action_type": "notification", "owner": "bad-user",
        "message": "Governance reminder"}}])
    api = NotificationAPI()
    result = run_queued_automation(repository=repo, api=api, now=datetime(2026, 11, 26, 12, tzinfo=timezone.utc))
    assert result["failed"] == 1
    assert result["retry_pending"] == 1
    assert repo.rows[0]["status"] == "Retry Pending"
    assert repo.rows[0]["next_retry_at"] == "2026-11-26T12:05:00+00:00"


def test_retry_pending_not_yet_due_is_skipped():
    repo = RunnerRepo([{"idempotency_key": "wait", "status": "Retry Pending", "attempts": 1,
        "next_retry_at": "2026-11-26T12:15:00+00:00", "action": {}}])
    result = run_queued_automation(repository=repo, now=datetime(2026, 11, 26, 12, tzinfo=timezone.utc))
    assert result["skipped"] == 1
    assert repo.updates == []


def test_api_execution_history_enforces_read_permission(monkeypatch):
    import velora_governance.api as api_module
    fake_frappe = SimpleNamespace(has_permission=lambda *args: True,
        get_list=lambda *args, **kwargs: [{"name": "GAE-1", "execution_status": "Queued"}],
        throw=lambda msg, exc=None: (_ for _ in ()).throw(RuntimeError(msg)),
        PermissionError=PermissionError)
    monkeypatch.setattr(api_module, "frappe", fake_frappe)
    rows = api_module.get_governance_automation_execution_history(status="Queued", limit=500, offset=-3)
    assert rows[0]["name"] == "GAE-1"

    fake_frappe.has_permission = lambda *args: False
    try:
        api_module.get_governance_automation_execution_history()
    except RuntimeError as exc:
        assert "permission" in str(exc).lower()
    else:
        raise AssertionError("read permission should be required")


def test_api_retry_requires_write_permission_and_failed_state(monkeypatch):
    import velora_governance.api as api_module
    doc = SimpleNamespace(name="GAE-1", execution_status="Failed", attempts=1, last_error="old",
        save=lambda **kwargs: setattr(doc, "saved", True), check_permission=lambda p: None)
    fake_frappe = SimpleNamespace(has_permission=lambda *args: True, get_doc=lambda *args: doc,
        throw=lambda msg, exc=None: (_ for _ in ()).throw(RuntimeError(msg)),
        PermissionError=PermissionError, utils=SimpleNamespace(now_datetime=lambda: "2026-11-26 12:00:00"))
    monkeypatch.setattr(api_module, "frappe", fake_frappe)
    result = api_module.retry_governance_automation_execution("GAE-1")
    assert result["status"] == "Retry Pending"
    assert doc.last_error == ""
    assert doc.saved

    doc.execution_status = "Completed"
    try:
        api_module.retry_governance_automation_execution("GAE-1")
    except RuntimeError as exc:
        assert "Only failed" in str(exc)
    else:
        raise AssertionError("completed executions must not be retried")


def test_scheduler_hooks_register_daily_generation_and_hourly_execution():
    import velora_governance.hooks as hooks
    assert "velora_governance.jobs.daily_generate_governance_automation" in hooks.scheduler_events["daily"]
    assert "velora_governance.jobs.hourly_execute_governance_automation" in hooks.scheduler_events["hourly"]


def test_notification_dispatch_rejects_disabled_user():
    class DisabledAPI(NotificationAPI):
        def get_list(self, doctype, filters=None, **kwargs):
            if doctype == "User":
                return [{"name": filters["name"], "enabled": 0}]
            return super().get_list(doctype, filters, **kwargs)
    try:
        dispatch_in_app_notification({"owner": "user@example.test", "message": "test"}, api=DisabledAPI())
    except ValueError as exc:
        assert str(exc) == "recipient_user_disabled"
    else:
        raise AssertionError("disabled users must not receive notifications")


class NativeRuntimeSimAPI:
    """Integration simulator for the native Document API surface used by this batch."""
    def __init__(self):
        self.execution_store = {}
        self.notification_store = {}
        self.source = {"Board Action": [{"name": "BA-100", "due_date": "2026-11-26",
            "action_status": "Open", "action_title": "Board action due today",
            "assigned_owner": "user@example.test", "governance_entity": "GE-1"}]}
    def get_list(self, doctype, filters=None, fields=None, limit=100, offset=0, ignore_permissions=False):
        if doctype in self.source:
            rows = list(self.source[doctype])
        elif doctype == "Governance Automation Execution":
            rows = [vars(d).copy() for d in self.execution_store.values()]
        elif doctype == "Notification Log":
            rows = [vars(d).copy() for d in self.notification_store.values()]
        elif doctype == "User":
            rows = [{"name": "user@example.test", "enabled": 1}]
        else:
            rows = []
        if isinstance(filters, list):
            for field, operator, value in filters:
                if operator == "in":
                    rows = [r for r in rows if r.get(field) in value]
                elif operator == "=":
                    rows = [r for r in rows if r.get(field) == value]
        else:
            for field, condition in (filters or {}).items():
                if isinstance(condition, (list, tuple)) and condition and condition[0] == "in":
                    rows = [r for r in rows if r.get(field) in condition[1]]
                else:
                    rows = [r for r in rows if r.get(field) == condition]
        return [{field: row.get(field) for field in (fields or [])} for row in rows[offset:offset+limit]]
    def new_doc(self, doctype):
        store = self.execution_store if doctype == "Governance Automation Execution" else self.notification_store
        doc = SimpleNamespace(doctype=doctype)
        def insert(ignore_permissions=False):
            doc.name = f"{doctype.replace(' ', '-')}-{len(store)+1}"
            store[doc.name] = doc
            return doc
        def save(ignore_permissions=False):
            store[doc.name] = doc
            return doc
        doc.insert = insert
        doc.save = save
        return doc
    def get_doc(self, doctype, name, ignore_permissions=False):
        return self.execution_store[name]


def test_native_document_api_pipeline_generates_persists_and_dispatches_once():
    api = NativeRuntimeSimAPI()
    generated = generate_and_persist_actions(api=api, today=date(2026, 11, 26))
    assert generated["persisted"] == 1
    assert len(api.execution_store) == 1
    key = next(iter(api.execution_store.values())).idempotency_key
    executed = run_queued_automation(api=api, now=datetime(2026, 11, 26, 12, tzinfo=timezone.utc))
    assert executed["completed"] == 1
    execution = next(iter(api.execution_store.values()))
    assert execution.execution_status == "Completed"
    assert execution.attempts == 1
    assert len(api.notification_store) == 1
    duplicate_generation = generate_and_persist_actions(api=api, today=date(2026, 11, 26))
    assert duplicate_generation["duplicates"] == 1
    duplicate_dispatch = dispatch_in_app_notification(execution_action := __import__("json").loads(execution.action_payload), api=api)
    assert duplicate_dispatch["duplicate_suppressed"] is True
    assert len(api.notification_store) == 1
    assert execution.idempotency_key == key
