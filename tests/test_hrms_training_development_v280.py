from pathlib import Path
import json
PROJECT=Path(__file__).resolve().parents[1]
HR=PROJECT/'apps/velora_erp/velora_erp/hr/doctype'

def test_training_doctypes_and_governance_metadata():
    expected={
      'training_course':['course_code','course_title','course_category','delivery_method','competency','active'],
      'training_program':['program_code','course','approval_status','start_date','end_date','budget_amount'],
      'training_session':['program','start_datetime','end_datetime','capacity','session_status'],
      'training_enrollment':['session','employee','status','attendance_status','assessment_score','development_plan'],
    }
    for slug,fields in expected.items():
        data=json.loads((HR/slug/f'{slug}.json').read_text())
        assert data['module']=='HR' and data['track_changes'] is True and data['istable'] is False
        names={f['fieldname'] for f in data['fields']}
        assert set(fields)<=names
        assert {'System Manager','HR Manager','HR Officer'} <= {p['role'] for p in data['permissions']}

def test_training_api_routes_and_client_methods():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app=FastAPI(); install_hr_routes(app,lambda request,fn: fn())
    routes={(r.path,tuple(sorted(r.methods or []))) for r in app.routes}
    assert ('/api/hr/training/catalog',('GET',)) in routes
    assert ('/api/hr/training/needs-analysis',('GET',)) in routes
    assert ('/api/hr/training/programs',('GET',)) in routes
    client=(PROJECT/'frontend/src/api.ts').read_text()
    for method in ('trainingCatalog','trainingNeedsAnalysis','trainingPrograms'):
        assert method in client

def test_training_controllers_enforce_business_rules():
    src=(HR/'training_enrollment/training_enrollment.py').read_text()
    assert 'between 0 and 100' in src
    assert 'requires recorded attendance' in src
    session=(HR/'training_session/training_session.py').read_text()
    assert 'must be after' in session
    program=(HR/'training_program/training_program.py').read_text()
    assert 'cannot precede' in program

def test_training_operations_routes_and_frontend_workspace():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app=FastAPI(); install_hr_routes(app,lambda request,fn: fn())
    routes={(r.path,tuple(sorted(r.methods or []))) for r in app.routes}
    assert ('/api/hr/training/operations',('GET',)) in routes
    assert ('/api/hr/training/analytics',('GET',)) in routes
    assert ('/api/hr/training/enrollments/{enrollment_name}/attendance',('POST',)) in routes
    assert ('/api/hr/training/enrollments/{enrollment_name}/certificate',('POST',)) in routes
    frontend=(PROJECT/'frontend/src/components/TrainingCentre.tsx').read_text()
    assert 'Training Centre' in frontend and 'Record certificate' in frontend
    assert 'trainingOperations' in (PROJECT/'frontend/src/api.ts').read_text()
