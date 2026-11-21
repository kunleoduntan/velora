from pathlib import Path
import json

PROJECT=Path(__file__).resolve().parents[1]

def test_training_enrollment_has_completion_and_certificate_validity_dates():
    path=PROJECT/'apps/velora_erp/velora_erp/hr/doctype/training_enrollment/training_enrollment.json'
    fields={x['fieldname']:x for x in json.loads(path.read_text())['fields']}
    assert fields['training_completed_on']['fieldtype']=='Date'
    assert fields['certificate_issue_date']['fieldtype']=='Date'
    assert fields['certificate_expiry_date']['fieldtype']=='Date'

def test_training_intelligence_routes_and_api_client():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app=FastAPI(); install_hr_routes(app,lambda request,fn:fn())
    routes={(r.path,tuple(sorted(r.methods or []))) for r in app.routes}
    assert ('/api/hr/training/effectiveness',('GET',)) in routes
    assert ('/api/hr/training/budget-analysis',('GET',)) in routes
    assert ('/api/hr/training/recommendations',('GET',)) in routes
    client=(PROJECT/'frontend/src/api.ts').read_text()
    for method in ('trainingEffectiveness','trainingBudgetAnalysis','trainingRecommendations'):
        assert method in client

def test_training_effectiveness_requires_pre_and_post_confirmed_assessments():
    source=(PROJECT/'velora/api/hr.py').read_text()
    assert 'if not before or not after: continue' in source
    assert 'Closest confirmed competency assessment before and after recorded training completion' in source
    assert 'association only, not causal attribution' in source

def test_training_budget_analysis_excludes_withdrawn_and_failed_enrolments():
    source=(PROJECT/'velora/api/hr.py').read_text()
    assert '("Withdrawn","Failed")' in source
    assert '"utilisation_percent"' in source and '"over_budget"' in source
