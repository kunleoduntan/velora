import json, sys
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
import pytest

PROJECT=Path(__file__).resolve().parents[1]
APP=str(PROJECT/'apps'/'velora_erp')
if APP not in sys.path: sys.path.insert(0,APP)


def registry():
    from velora.meta.registry import Registry
    r=Registry(); r.load(['velora_erp']); return r


def test_attendance_integration_doctypes_register():
    r=registry()
    expected={'Attendance Integration','Attendance Device','Attendance Device User Mapping','External Attendance Punch','Attendance Sync Run'}
    assert expected.issubset(set(r._doctypes))


def test_provider_catalogue_distinguishes_native_and_gateway_adapters():
    from velora_erp.hr.attendance_integrations import PROVIDERS
    assert PROVIDERS['ZKTeco BioTime']['mode']=='REST API Pull'
    assert PROVIDERS['ZKTeco BioTime']['status']=='Native REST report connector'
    assert PROVIDERS['ZKTeco ADMS Gateway']['mode']=='Normalised Event Push'
    assert 'gateway' in PROVIDERS['Suprema']['status'].lower()


def test_integration_config_requires_https_and_env_secret_reference():
    from velora_erp.hr.doctype.attendance_integration.attendance_integration import AttendanceIntegration
    from velora.exceptions import ValidationError
    doc=AttendanceIntegration.__new__(AttendanceIntegration)
    doc.page_size=100; doc.transport='REST API Pull'; doc.provider='ZKTeco BioTime'; doc.api_base_url='http://example.com'; doc.credential_env='BIO_TOKEN'
    with pytest.raises(Exception): doc.validate()
    doc.api_base_url='https://biotime.example.com'; doc.credential_env='BIO_TOKEN'; doc.validate()


def test_integration_config_rejects_plaintext_or_invalid_credential_env_name():
    from velora_erp.hr.doctype.attendance_integration.attendance_integration import AttendanceIntegration
    doc=AttendanceIntegration.__new__(AttendanceIntegration)
    doc.page_size=100; doc.transport='REST API Pull'; doc.api_base_url='https://biotime.example.com'; doc.credential_env='not a secret value'
    with pytest.raises(Exception): doc.validate()


def test_biotime_timestamp_report_conversion_uses_integration_timezone():
    from velora_erp.hr.attendance_integrations import _dt
    value=_dt('2026-11-16T08:15:00','Africa/Lagos')
    assert value == datetime(2026,11,16,8,15)


def test_punch_event_key_is_stable_and_sensitive_to_event_identity():
    from velora_erp.hr.attendance_integrations import _key
    a=_key('BIO','SN-1','E-1','2026-11-16T08:00:00','event-1','0')
    b=_key('BIO','SN-1','E-1','2026-11-16T08:00:00','event-1','0')
    c=_key('BIO','SN-1','E-1','2026-11-16T08:00:00','event-2','0')
    corrected=_key('BIO','SN-1','E-1','2026-11-16T08:01:00','event-1','1')
    assert len(a)==64 and a==b and a!=c and a==corrected


def test_device_user_mapping_requires_stable_composite_key(monkeypatch):
    import velora_erp.hr.doctype.attendance_device_user_mapping.attendance_device_user_mapping as mod
    monkeypatch.setattr(mod,'get_list',lambda *a,**k: [])
    doc=mod.AttendanceDeviceUserMapping.__new__(mod.AttendanceDeviceUserMapping)
    doc.integration='BIO'; doc.device='TERM-1'; doc.external_user_id='0007'; doc.effective_from='2026-01-01'; doc.effective_to='2026-12-31'; doc.name='MAP-1'
    doc.validate()
    assert doc.mapping_key=='BIO:TERM-1:0007'


def test_external_punch_requires_sha256_key_and_employee_time():
    from velora_erp.hr.doctype.external_attendance_punch.external_attendance_punch import ExternalAttendancePunch
    doc=ExternalAttendancePunch.__new__(ExternalAttendancePunch)
    doc.external_event_key='bad'; doc.external_user_id='001'; doc.punch_datetime='2026-11-16 08:00:00'; doc.processing_status='Received'; doc.attendance=None
    with pytest.raises(Exception): doc.validate()


def test_biotime_api_connector_is_environment_secret_based():
    source=(PROJECT/'apps'/'velora_erp'/'velora_erp'/'hr'/'attendance_integrations.py').read_text()
    assert 'os.environ.get(env_name)' in source
    assert 'Authorization":"JWT "' in source
    assert 'api-token' not in source.lower()  # no unverified token-issuance endpoint is assumed


def test_attendance_integration_routes_are_installed():
    source=(PROJECT/'velora'/'api'/'hr.py').read_text()
    for route in ('/api/hr/attendance-integrations/providers','/punches','/reconcile','/sync-biotime'):
        assert route in source


def test_new_hr_metadata_uses_supported_field_types():
    root=PROJECT/'apps'/'velora_erp'/'velora_erp'/'hr'/'doctype'
    supported={'Data','Text','Int','Float','Currency','Check','Date','Datetime','Select','Link','JSON','Section Break','Column Break','Tab Break','Table'}
    for name in ('attendance_integration','attendance_device','attendance_device_user_mapping','external_attendance_punch','attendance_sync_run'):
        d=json.loads((root/name/(name+'.json')).read_text())
        assert d['module']=='HR'
        assert all(f['fieldtype'] in supported for f in d['fields'])


def test_attendance_source_supports_integration_generated_records():
    d=registry()._doctypes['Attendance']
    assert 'Integration' in d.get_field('attendance_source').choices
    assert d.get_field('approval_status')


def test_normalised_ingestion_maps_employee_and_creates_idempotency_key(monkeypatch):
    import velora_erp.hr.attendance_integrations as mod
    monkeypatch.setattr(mod,'get_doc',lambda *a,**k: SimpleNamespace(active=1,timezone='Africa/Lagos'))
    def fake_list(doctype,filters=None,**kwargs):
        if doctype=='Attendance Device': return [{'name':'TERM-1','timezone':'Africa/Lagos'}]
        if doctype=='Attendance Device User Mapping': return [{'name':'MAP-1','device':'TERM-1','employee':'EMP-1','effective_from':'2026-01-01','effective_to':'2026-12-31'}]
        if doctype=='External Attendance Punch': return []
        return []
    monkeypatch.setattr(mod,'get_list',fake_list)
    saved=[]
    class FakeDoc:
        def __init__(self,**kw): self.values=kw
        def insert(self,ignore_permissions=False): saved.append(self.values); self.name='PUNCH-1'
    monkeypatch.setattr(mod,'new_doc',lambda doctype,**kw: FakeDoc(**kw))
    result=mod.ingest_events('ZK-1',[{'serial_number':'SN-1','user_id':'0001','timestamp':'2026-11-16 08:00:00','event_id':'E-1'}])
    assert result['created']==1 and result['unmapped']==0
    assert saved[0]['employee']=='EMP-1'
    assert saved[0]['processing_status']=='Ready'
    assert len(saved[0]['external_event_key'])==64


def test_biotime_report_connector_stages_first_and_last_punch_events(monkeypatch):
    import velora_erp.hr.attendance_integrations as mod
    integration=SimpleNamespace(provider='ZKTeco BioTime',transport='REST API Pull',active=1,
        credential_env='TEST_ZK_TOKEN',api_base_url='https://biotime.example.com',
        attendance_endpoint='/att/api/firstLastReport/',timezone='Africa/Lagos',page_size=100,
        last_sync_on=None,save=lambda **kw: None)
    monkeypatch.setattr(mod,'get_doc',lambda *a,**k: integration)
    monkeypatch.setenv('TEST_ZK_TOKEN','test-jwt')
    class Run:
        name='SYNC-1'
        def insert(self,**kw): pass
        def save(self,**kw): pass
    monkeypatch.setattr(mod,'new_doc',lambda *a,**k: Run())
    monkeypatch.setattr(mod,'_https_json',lambda *a,**k:{'data':[{'emp_code':'E-1','att_date':'2026-11-16','first_punch':'08:00 AM','last_punch':'05:00 PM'}],'next':None})
    staged=[]
    monkeypatch.setattr(mod,'ingest_events',lambda name,events,source=None:(staged.extend(events) or {'created':2,'duplicates':0,'unmapped':0,'errors':[]}))
    monkeypatch.setattr(mod,'reconcile_punches',lambda *a,**k:{'attendance_created':1,'conflicts':0,'needs_review':0})
    result=mod.sync_biotime_report('ZK-BIOTIME','2026-11-16','2026-11-16')
    assert result['created']==1 and result['fetched']==1
    assert len(staged)==2
    assert {x['punch_state'] for x in staged}=={'IN','OUT'}
    assert all(x['external_user_id']=='E-1' for x in staged)
