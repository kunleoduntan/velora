import json, sys
from pathlib import Path
from types import SimpleNamespace
import pytest

PROJECT=Path(__file__).resolve().parents[1]
APP=str(PROJECT/'apps'/'velora_erp')
if APP not in sys.path: sys.path.insert(0,APP)


def test_performance_doctypes_register_and_relationships():
    from velora.meta.registry import Registry
    r=Registry(); r.load(['velora_erp'])
    expected={'Performance Cycle','Performance Review Template','Performance Template Criterion','Performance Goal','Performance Check In','Performance Review','Performance Review Rating','Performance Feedback','Performance Improvement Plan','Performance Development Action'}
    assert expected <= set(r._doctypes)
    assert r._doctypes['Performance Template Criterion'].istable
    assert r._doctypes['Performance Review Rating'].istable


def test_weighted_template_requires_100_percent():
    from velora_erp.hr.doctype.performance_review_template.performance_review_template import PerformanceReviewTemplate
    doc=object.__new__(PerformanceReviewTemplate)
    doc.criteria=[SimpleNamespace(criterion_code='DELIVERY',weight=60),SimpleNamespace(criterion_code='QUALITY',weight=30)]
    doc.rating_method='Weighted Average'
    with pytest.raises(Exception,match='total 100%'): doc.validate()
    doc.criteria[1].weight=40
    doc.validate()


def test_performance_review_calculates_weighted_score_and_rating(monkeypatch):
    import velora_erp.hr.doctype.performance_review.performance_review as mod
    criteria=[SimpleNamespace(criterion_code='GOAL',weight=70,mandatory=1),SimpleNamespace(criterion_code='BEHAVIOUR',weight=30,mandatory=1)]
    template=SimpleNamespace(rating_method='Weighted Average',criteria=criteria)
    cycle=SimpleNamespace(status='Review',review_template='TPL')
    monkeypatch.setattr(mod,'get_doc',lambda dt,name,**kw: cycle if dt=='Performance Cycle' else template)
    doc=object.__new__(mod.PerformanceReview)
    doc.cycle='PC-2026'; doc.review_status='Pending Approval'; doc.ratings=[SimpleNamespace(criterion_code='GOAL',weight=0,final_rating=4),SimpleNamespace(criterion_code='BEHAVIOUR',weight=0,final_rating=3)]
    doc.calibrated_score=None; doc.overall_score=0; doc.overall_rating=None
    doc.validate()
    assert doc.overall_score==3.7
    assert doc.overall_rating=='Exceeds Expectations'


def test_goal_progress_is_derived_from_baseline_and_target():
    from velora_erp.hr.doctype.performance_goal.performance_goal import PerformanceGoal
    doc=object.__new__(PerformanceGoal)
    doc.weight=20; doc.progress_percent=0; doc.start_date='2026-01-01'; doc.due_date='2026-12-31'; doc.parent_goal=None; doc.cycle='PC-26'; doc.target_value=100; doc.baseline=20; doc.actual_value=60; doc.status='In Progress'
    doc.validate()
    assert doc.progress_percent==50


def test_dashboard_and_hr_workspace_expose_performance_centre():
    routes=(PROJECT/'velora'/'api'/'hr.py').read_text()
    assert '/api/hr/performance/dashboard' in routes
    setup=(PROJECT/'apps'/'velora_erp'/'velora_erp'/'setup.py').read_text()
    for name in ('Performance Cycles','Review Templates','Performance Goals','Performance Check-ins','Performance Reviews','360 Feedback','Improvement Plans'):
        assert name in setup


def test_payroll_finance_code_is_not_replaced_by_performance_release():
    hooks=(PROJECT/'apps'/'velora_erp'/'velora_erp'/'hooks.py').read_text()
    assert 'process_due_recognitions' in hooks
    assert 'process_due_accrual_reversals' in hooks
    assert 'run_scheduled_attendance_syncs' in hooks


def test_performance_dashboard_route_is_registered():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app=FastAPI()
    install_hr_routes(app,lambda request,fn: fn())
    assert any(r.path=='/api/hr/performance/dashboard' for r in app.routes)
