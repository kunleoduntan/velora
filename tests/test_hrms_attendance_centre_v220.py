import json, sys
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
import pytest

PROJECT=Path(__file__).resolve().parents[1]
APP=str(PROJECT/'apps'/'velora_erp')
if APP not in sys.path: sys.path.insert(0,APP)


def test_attendance_integration_centre_fields_and_routes():
    root=PROJECT/'apps'/'velora_erp'/'velora_erp'/'hr'/'doctype'
    integration=json.loads((root/'attendance_integration'/'attendance_integration.json').read_text())
    device=json.loads((root/'attendance_device'/'attendance_device.json').read_text())
    fields={x['fieldname'] for x in integration['fields']}
    assert {'auto_sync_enabled','sync_frequency','lookback_days','health_status','last_successful_sync_on','consecutive_failures'}<=fields
    assert {'health_status','last_event_on','last_health_check'}<={x['fieldname'] for x in device['fields']}
    routes=(PROJECT/'velora'/'api'/'hr.py').read_text()
    for path in ('test-connection','mapping-suggestions','health/summary'):
        assert path in routes


def test_provider_catalogue_keeps_native_biotime_and_multiple_adapter_contracts():
    from velora_erp.hr.attendance_integrations import PROVIDERS
    assert PROVIDERS['ZKTeco BioTime']['mode']=='REST API Pull'
    assert 'gateway' in PROVIDERS['Hikvision']['status'].lower()
    assert 'CSV Import' in PROVIDERS


def test_exact_mapping_suggestions_never_auto_link(monkeypatch):
    import velora_erp.hr.attendance_integrations as mod
    def fake_list(doctype,filters=None,**kwargs):
        if doctype=='External Attendance Punch':
            return [{'external_user_id':'0007','device':'D1','serial_number':'SN1'}, {'external_user_id':'0007','device':'D1','serial_number':'SN1'}]
        if doctype=='Employee': return [{'name':'EMP-7','employee_code':'0007','employee_name':'Test Person'}]
        return []
    monkeypatch.setattr(mod,'get_list',fake_list)
    result=mod.suggest_device_user_mappings('BIO')
    assert len(result)==1
    assert result[0]['suggested_employee']=='EMP-7'
    assert result[0]['requires_hr_confirmation'] is True


def test_scheduled_sync_only_runs_opted_in_due_biotime(monkeypatch):
    import velora_erp.hr.attendance_integrations as mod
    now=datetime.now(mod.timezone.utc)
    monkeypatch.setattr(mod,'datetime',SimpleNamespace(now=lambda *a,**k:now))
    monkeypatch.setattr(mod,'get_list',lambda doctype,**kw: (
        [{'name':'BIO-1','provider':'ZKTeco BioTime','sync_frequency':'Hourly','last_sync_on':None,'lookback_days':2}]
        if doctype=='Attendance Integration' else []))
    calls=[]
    monkeypatch.setattr(mod,'sync_biotime_report',lambda name,start,end: calls.append((name,start,end)) or {'created':1})
    result=mod.run_scheduled_attendance_syncs()
    assert len(calls)==1 and result[0]['status']=='Completed'


def test_shift_work_date_assigns_overnight_punch_to_shift_start_day(monkeypatch):
    import velora_erp.hr.attendance_integrations as mod
    def fake_list(doctype,**kwargs):
        if doctype=='Shift Assignment':
            return [{'shift_type':'NIGHT','effective_from':'2026-11-01','effective_to':'2026-11-30','days_of_week':['Monday']}]
        return []
    monkeypatch.setattr(mod,'get_list',fake_list)
    monkeypatch.setattr(mod,'get_doc',lambda doctype,name,**kw: SimpleNamespace(start_time='22:00',end_time='06:00',crosses_midnight=1))
    # Tuesday 02:00 belongs to Monday's overnight shift.
    assert mod._shift_work_date('EMP-1',datetime(2026,11,17,2,0)) .isoformat()=='2026-11-16'


def test_hourly_scheduler_is_registered():
    hooks=(PROJECT/'apps'/'velora_erp'/'velora_erp'/'hooks.py').read_text()
    assert '"every_minute"' in hooks
    assert 'run_scheduled_attendance_syncs' in hooks
