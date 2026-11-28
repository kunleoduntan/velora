from datetime import datetime, timedelta
from velora_governance.governance.services.governance_exception_activity import activity_key
from velora_governance.governance.services.governance_exception_escalation import determine_due_stage, escalation_recipients, workload_metrics
from velora_governance.governance.services.governance_exception_configuration import validate_exception_configuration


def test_escalation_intervals_validate_and_normalize():
    result = validate_exception_configuration({"escalation_after_hours":"24,72,168","escalation_targets":{"1":["user@example.com"]}})
    assert result["valid"]
    assert result["normalized"]["escalation_after_hours"] == "24,72,168"
    assert result["normalized"]["escalation_targets"] == {"1":["user@example.com"]}


def test_escalation_interval_rejects_nonincreasing_values():
    result = validate_exception_configuration({"escalation_after_hours":"24,24,48"})
    assert not result["valid"]
    assert "escalation_intervals_must_be_positive_and_increasing" in result["errors"]


def test_escalation_stage_based_on_elapsed_time():
    created = datetime(2026, 1, 1, 0, 0)
    assert determine_due_stage(created, created + timedelta(hours=23), "24,72,168") is None
    assert determine_due_stage(created, created + timedelta(hours=25), "24,72,168") == 1
    assert determine_due_stage(created, created + timedelta(hours=80), "24,72,168", completed_stages=1) == 2
    assert determine_due_stage(created, created + timedelta(hours=200), "24,72,168", completed_stages=3) is None


def test_escalation_recipients_deduplicated_and_empty_when_unconfigured():
    assert escalation_recipients({"1":["u1","u1"," u2 "]}, 1) == ["u1","u2"]
    assert escalation_recipients({}, 2) == []


def test_activity_key_deterministic_and_source_sensitive():
    a = activity_key("GE-1","Comment",actor="u1",details="hello")
    assert a == activity_key("GE-1","Comment",actor="u1",details="hello")
    assert a != activity_key("GE-1","Comment",actor="u1",details="other")


def test_workload_metrics_aggregate_owner_and_age_buckets():
    rows = [
        {"status":"Open","assigned_to":"u1","age_days":4},
        {"status":"Escalated","assigned_to":"u1","age_days":45},
        {"status":"In Progress","assigned_to":None,"age_days":75},
        {"status":"Closed","assigned_to":"u2","age_days":90},
    ]
    result = workload_metrics(rows)
    assert result["active"] == 3
    assert result["escalated"] == 1
    assert result["unassigned"] == 1
    assert result["by_owner"] == {"u1":2,"Unassigned":1}
    assert result["aging_buckets"] == {"0_7":1,"8_30":0,"31_60":1,"61_plus":1}


def test_append_activity_idempotent_with_fake_api():
    from velora_governance.governance.services.governance_exception_activity import append_activity
    class FakeDoc:
        name = "GEA-1"
        def insert(self, ignore_permissions=False):
            api.rows.append({"name":self.name,"idempotency_key":self.idempotency_key})
    class FakeAPI:
        rows=[]
        def get_list(self, doctype, filters=None, fields=None, limit_page_length=1):
            return [r for r in self.rows if r.get("idempotency_key")==filters.get("idempotency_key")]
        def get_doc(self, data):
            d=FakeDoc()
            for k,v in data.items(): setattr(d,k,v)
            return d
    api=FakeAPI()
    one=append_activity("GE-1","Comment",actor="u1",details="note",api=api)
    two=append_activity("GE-1","Comment",actor="u1",details="note",api=api)
    assert one["created"] is True and two["created"] is False


def test_runtime_escalation_notifies_enabled_targets_and_records_stage():
    from velora_governance.governance.services.governance_exception_escalation_runtime import run_exception_escalations
    from datetime import datetime
    class FakeDoc:
        def __init__(self, data): self.data=data; self.name="NL-1"
        def insert(self, ignore_permissions=False):
            if self.data.get("doctype") == "Notification Log": api.notifications.append(self.data)
            elif self.data.get("doctype") == "Governance Exception Activity": api.activity.append(self.data)
    class FakeAPI:
        notifications=[]; activity=[]
        def get_single(self, doctype):
            return type("Config",(),{"escalation_after_hours":"24,72","escalation_targets":{"1":["u1"]}})()
        def get_list(self, doctype, filters=None, fields=None, limit_page_length=100):
            if doctype=="Governance Exception": return [{"name":"GE-1","title":"Late Filing","severity":"High","status":"Open","assigned_to":None,"creation":datetime(2026,1,1)}]
            if doctype=="Governance Exception Activity": return [r for r in self.activity if (filters.get("exception") and r.get("exception")==filters.get("exception")) or (filters.get("idempotency_key") and r.get("idempotency_key")==filters.get("idempotency_key"))]
            if doctype=="User": return [{"name":"u1"}] if filters.get("name")=="u1" else []
            return []
        def get_doc(self, data):
            if data.get("doctype")=="Notification Log": return FakeDoc(data)
            return FakeDoc(data)
    api=FakeAPI()
    result=run_exception_escalations(api=api,now=datetime(2026,1,2,2))
    assert result["escalated"]==1 and result["notifications"]==1
    assert api.notifications[0]["for_user"]=="u1"
    second=run_exception_escalations(api=api,now=datetime(2026,1,2,2))
    assert second["notifications"]==0
