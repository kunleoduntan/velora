from pathlib import Path
import json
PROJECT=Path(__file__).resolve().parents[1]
HR=PROJECT/'apps/velora_erp/velora_erp/hr/doctype'

def test_v260_domain_doctypes_are_registered_metadata():
    expected=['performance_cycle_assignment','career_development_plan','critical_position','succession_candidate']
    for slug in expected:
        data=json.loads((HR/slug/f'{slug}.json').read_text())
        assert data['module']=='HR' and data['track_changes'] is True
        assert data['fields']

def test_succession_confidentiality_is_restricted_by_default():
    data=json.loads((HR/'succession_candidate/succession_candidate.json').read_text())
    field=next(f for f in data['fields'] if f['fieldname']=='confidentiality_level')
    assert field['default']=='HR Restricted'

def test_v260_routes_registered():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app=FastAPI(); install_hr_routes(app,lambda request,fn: fn())
    paths={r.path for r in app.routes}
    assert '/api/hr/performance/cycles/{cycle_name}/assignment-preview' in paths
    assert '/api/hr/performance/cycles/{cycle_name}/assign' in paths
    assert '/api/hr/performance/intelligence/trends' in paths
    assert '/api/hr/succession/overview' in paths
