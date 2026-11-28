from datetime import date
from types import SimpleNamespace
import sys

from velora_admin.administration import renewal_management as rm

class FakeFrappe:
    rows = []
    def get_all(self, *args, **kwargs):
        return self.rows


def test_scan_emits_configured_milestone_and_idempotency_key(monkeypatch):
    fake = FakeFrappe()
    fake.rows = [SimpleNamespace(name="REN-1", renewal_title="Operating License", renewal_category="License",
        expiry_date="2026-12-25", notification_schedule_json="[30,14,7,1,0]", department="Admin",
        responsible_officer="USER-1", company_or_entity="COMP-1")]
    monkeypatch.setitem(sys.modules, "frappe", fake)
    result = rm.daily_renewal_scan(date(2026, 11, 25))
    assert len(result["events"]) == 1
    event = result["events"][0]
    assert event["days_remaining"] == 30
    assert event["idempotency_key"] == "renewal:REN-1:30:2026-11-25"
    assert result["dispatch_status"] == "PENDING_FRAMEWORK_NOTIFICATION_ENGINE_API"


def test_scan_malformed_schedule_falls_back_to_default(monkeypatch):
    fake = FakeFrappe()
    fake.rows = [SimpleNamespace(name="REN-2", renewal_title="Permit", renewal_category="Permit",
        expiry_date="2026-12-25", notification_schedule_json="invalid", department=None,
        responsible_officer=None, company_or_entity=None)]
    monkeypatch.setitem(sys.modules, "frappe", fake)
    result = rm.daily_renewal_scan(date(2026, 11, 25))
    assert result["events"][0]["days_remaining"] == 30



def test_scan_non_list_schedule_falls_back(monkeypatch):
    fake = FakeFrappe()
    fake.rows = [SimpleNamespace(name="REN-3", renewal_title="Subscription", renewal_category="Subscription",
        expiry_date="2026-12-25", notification_schedule_json="30", department=None,
        responsible_officer=None, company_or_entity=None)]
    monkeypatch.setitem(sys.modules, "frappe", fake)
    result = rm.daily_renewal_scan(date(2026, 11, 25))
    assert result["events"][0]["days_remaining"] == 30
