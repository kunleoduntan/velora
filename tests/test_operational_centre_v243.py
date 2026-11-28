from fastapi.testclient import TestClient
from velora.api import create_app

ADMIN={"X-Velora-User":"boss","X-Velora-Roles":"System Manager"}

def test_operational_centre_excludes_employee_level_draft_salary_slips():
    from velora.api.operational_centre import QUEUES
    assert not any(doctype == "Salary Slip" for _, doctype, *_ in QUEUES)
    assert not any("salary slip" in label.lower() for _, _, label, *_ in QUEUES)

def test_operational_centre_uses_payroll_run_approval_queue():
    from velora.api.operational_centre import QUEUES
    payroll = [x for x in QUEUES if x[0] == "Payroll"]
    assert payroll == [("Payroll", "Payroll Run", "Payroll runs awaiting approval",
                        {"status": "Pending Approval", "approval_status": "Pending"},
                        "#/app/Payroll%20Run")]

def test_payroll_exception_queue_is_counted_at_run_level(monkeypatch):
    from velora.api import operational_centre as module
    calls=[]
    def fake_count(doctype, filters):
        calls.append((doctype, filters))
        return 3
    monkeypatch.setattr(module, "_safe_count", fake_count)
    payroll = [x for x in module.QUEUES if x[0] == "Payroll"]
    area, doctype, label, filters, route = payroll[0]
    assert module._safe_count(doctype, filters) == 3
    assert calls == [("Payroll Run", {"status":"Pending Approval", "approval_status":"Pending"})]
