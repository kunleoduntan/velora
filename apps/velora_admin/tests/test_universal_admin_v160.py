import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_v160_api_routes_registered():
    api=(ROOT/"velora_admin"/"administration"/"api.py").read_text()
    paths=set()
    import re
    paths.update(re.findall(r'@app\.(?:get|post|put|delete)\("([^"]+)"',api))
    expected={
      '/api/admin/universal/tasks/{name}/complete',
      '/api/admin/universal/work-orders',
      '/api/admin/universal/work-orders/{name}/complete',
      '/api/admin/universal/fleet/alerts',
      '/api/admin/universal/supplies/transactions',
      '/api/admin/universal/fleet/trip-conflicts',
      '/api/admin/universal/events/venue-conflicts',
      '/api/admin/universal/automation/run-daily',
    }
    assert expected.issubset(paths)


def test_v160_recurrence_and_automation_allowlist():
    from velora_admin.administration import universal_admin as ua
    assert ua._next_date('2026-11-25','Weekly').isoformat()=='2026-12-02'
    assert ua._next_date('2026-11-25','None') is None
    assert ua.ALLOWED_ACTIONS == {'create_task','set_priority','send_notification'}
    assert not any('approval' in action for action in ua.ALLOWED_ACTIONS)


def test_v160_operational_doctypes_fields_and_scheduler():
    dt=ROOT/'velora_admin'/'administration'/'doctype'
    stock=json.loads((dt/'stock_transaction'/'stock_transaction.json').read_text())
    task=json.loads((dt/'task'/'task.json').read_text())
    vehicle=json.loads((dt/'administrative_vehicle'/'administrative_vehicle.json').read_text())
    assert {'item','transaction_type','quantity'}.issubset({f['fieldname'] for f in stock['fields']})
    assert {'recurrence','due_date','status'}.issubset({f['fieldname'] for f in task['fields']})
    assert {'service_due_date','insurance_expiry','registration_expiry'}.issubset({f['fieldname'] for f in vehicle['fields']})
    hooks=(ROOT/'velora_admin'/'hooks.py').read_text()
    assert 'universal_admin.run_daily_admin_automation' in hooks


def test_v160_no_approval_workflow_hardcoded():
    module=(ROOT/'velora_admin'/'administration'/'universal_admin.py').read_text().lower()
    assert 'approval workflow' in module
    assert 'approval_level' not in module
    assert 'hardcoded_approver' not in module
