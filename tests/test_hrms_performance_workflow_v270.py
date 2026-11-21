from pathlib import Path
import json
PROJECT=Path(__file__).resolve().parents[1]
HR=PROJECT/'apps/velora_erp/velora_erp/hr/doctype'

def test_reminder_doctype_metadata_and_idempotency():
    data=json.loads((HR/'performance_workflow_reminder/performance_workflow_reminder.json').read_text())
    assert data['module']=='HR' and data['track_changes'] is True
    fields={f['fieldname']:f for f in data['fields']}
    assert fields['idempotency_key']['unique'] is True
    assert fields['status']['default']=='Queued'
    assert 'Sent' in fields['status']['options']

def test_v270_reminder_routes_registered():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app=FastAPI(); install_hr_routes(app,lambda request,fn: fn())
    routes={(r.path, tuple(sorted(r.methods or []))) for r in app.routes}
    assert ('/api/hr/performance/workflow/reminders/preview',('POST',)) in routes
    assert ('/api/hr/performance/workflow/reminders/queue',('POST',)) in routes
    assert ('/api/hr/performance/workflow/reminders',('GET',)) in routes

def test_v270_api_client_has_reminder_methods():
    source=(PROJECT/'frontend/src/api.ts').read_text()
    assert 'performanceReminderPreview' in source
    assert 'performanceReminderQueue' in source
    assert 'performanceReminderInbox' in source
