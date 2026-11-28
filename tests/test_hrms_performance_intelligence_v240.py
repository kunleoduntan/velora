import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
PROJECT=Path(__file__).resolve().parents[1]
APP=str(PROJECT/'apps'/'velora_erp')
if APP not in sys.path: sys.path.insert(0,APP)


def test_v240_performance_doctypes_register():
    from velora.meta.registry import Registry
    r=Registry(); r.load(['velora_erp','velora_projectone'])
    expected={'Competency','Competency Framework','Competency Framework Item','Employee Competency Assessment','Performance Calibration Item','Performance Calibration Session','Performance Rater Nomination','Performance Rater Campaign'}
    assert expected <= set(r._doctypes)
    assert r._doctypes['Competency Framework Item'].istable
    assert r._doctypes['Performance Calibration Item'].istable
    assert r._doctypes['Performance Rater Nomination'].istable


def test_competency_framework_requires_unique_competencies_and_weight_total():
    from velora_erp.hr.doctype.competency_framework.competency_framework import CompetencyFramework
    doc=object.__new__(CompetencyFramework)
    doc.applies_to='Organisation'; doc.competencies=[SimpleNamespace(competency='COMM',required_level=4,weight=60),SimpleNamespace(competency='LEAD',required_level=3,weight=30)]
    doc.effective_from='2026-01-01'; doc.effective_to='2026-12-31'
    with pytest.raises(Exception,match='total 100%'): doc.validate()
    doc.competencies[1].weight=40; doc.validate()
    doc.competencies[1].competency='COMM'
    with pytest.raises(Exception,match='only once'): doc.validate()


def test_competency_assessment_calculates_gap_and_requires_evidence():
    from velora_erp.hr.doctype.employee_competency_assessment.employee_competency_assessment import EmployeeCompetencyAssessment
    doc=object.__new__(EmployeeCompetencyAssessment)
    doc.current_level=2; doc.required_level=4; doc.gap_level=0; doc.evidence=''; doc.status='Submitted'
    with pytest.raises(Exception,match='evidence'): doc.validate()
    doc.evidence='Completed two supervised projects'; doc.validate()
    assert doc.gap_level==2


def test_calibration_preserves_original_score_and_requires_rationale(monkeypatch):
    import velora_erp.hr.doctype.performance_calibration_session.performance_calibration_session as mod
    cycle=SimpleNamespace(status='Calibration')
    review=SimpleNamespace(cycle='C-26',overall_score=3.8,overall_rating='Exceeds Expectations')
    monkeypatch.setattr(mod,'get_doc',lambda dt,name,**kw: cycle if dt=='Performance Cycle' else review)
    doc=object.__new__(mod.PerformanceCalibrationSession)
    doc.cycle='C-26'; doc.status='In Progress'; doc.calibration_items=[SimpleNamespace(review='R-1',proposed_score=4.0,rationale='',decision='Accepted')]
    with pytest.raises(Exception,match='rationale'): doc.validate()
    doc.calibration_items[0].rationale='Evidence supports higher rating'; doc.validate()
    assert doc.calibration_items[0].original_score==3.8
    assert doc.calibration_items[0].original_rating=='Exceeds Expectations'


def test_rater_campaign_rejects_self_ratings_and_tracks_completion(monkeypatch):
    import velora_erp.hr.doctype.performance_rater_campaign.performance_rater_campaign as mod
    monkeypatch.setattr(mod,'get_doc',lambda *a,**k: SimpleNamespace(status='Active'))
    doc=object.__new__(mod.PerformanceRaterCampaign)
    doc.cycle='C-26'; doc.review=None; doc.opens_on='2026-01-01'; doc.closes_on='2026-12-31'; doc.minimum_raters=2; doc.status='Open'
    doc.nominations=[SimpleNamespace(rater='E-1',employee='E-1',status='Nominated')]
    with pytest.raises(Exception,match='cannot provide'): doc.validate()
    doc.nominations=[SimpleNamespace(rater='E-2',employee='E-1',status='Submitted'),SimpleNamespace(rater='E-3',employee='E-1',status='Nominated')]
    doc.validate(); assert doc.completion_percent==50.0


def test_performance_intelligence_dashboard_contract_and_workspace():
    source=(PROJECT/'velora'/'api'/'hr.py').read_text()
    for token in ('competency_gaps','feedback_campaigns','calibration','department_performance','development_actions'):
        assert token in source
    setup=(PROJECT/'apps'/'velora_erp'/'velora_erp'/'setup.py').read_text()
    for title in ('Competency Library','Competency Frameworks','Skills Gap Assessments','Calibration Sessions','360 Feedback Campaigns'):
        assert title in setup


def test_existing_payroll_finance_and_attendance_schedulers_preserved():
    hooks=(PROJECT/'apps'/'velora_erp'/'velora_erp'/'hooks.py').read_text()
    assert 'run_scheduled_attendance_syncs' in hooks
    assert 'process_due_recognitions' in hooks
    assert 'process_due_accrual_reversals' in hooks


def test_calibration_apply_endpoint_is_registered():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app=FastAPI(); install_hr_routes(app,lambda request,fn: fn())
    assert any(r.path=='/api/hr/performance/calibration/{session_name}/apply' for r in app.routes)


def test_competency_framework_requires_scope_for_role_specific_framework():
    from velora_erp.hr.doctype.competency_framework.competency_framework import CompetencyFramework
    doc=object.__new__(CompetencyFramework)
    doc.applies_to='Department'; doc.department=None; doc.competencies=[SimpleNamespace(competency='COMM',required_level=3,weight=0)]
    doc.effective_from=None; doc.effective_to=None
    with pytest.raises(Exception,match='Select Department'): doc.validate()


def test_completed_rater_campaign_requires_minimum_responses_per_employee(monkeypatch):
    import velora_erp.hr.doctype.performance_rater_campaign.performance_rater_campaign as mod
    monkeypatch.setattr(mod,'get_doc',lambda *a,**k: SimpleNamespace(status='Active'))
    doc=object.__new__(mod.PerformanceRaterCampaign)
    doc.cycle='C-26'; doc.review=None; doc.opens_on='2026-01-01'; doc.closes_on='2026-12-31'; doc.minimum_raters=2; doc.status='Completed'
    doc.nominations=[SimpleNamespace(rater='E-2',employee='E-1',status='Submitted'),SimpleNamespace(rater='E-3',employee='E-1',status='Nominated')]
    with pytest.raises(Exception,match='every employee'): doc.validate()
    doc.nominations[1].status='Submitted'; doc.validate()
    assert doc.completion_percent==100.0
