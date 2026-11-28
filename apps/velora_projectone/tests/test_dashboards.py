from decimal import Decimal
import pytest
from velora_projectone.projectone.reports.dashboards import (
    DASHBOARDS, build_dashboard_suite, portfolio_dashboard, financial_dashboard,
    delivery_dashboard, resource_dashboard, commercial_dashboard, risk_dashboard,
    agile_dashboard, quality_dashboard, schedule_dashboard,
)


def test_dashboard_suite_contains_all_enterprise_views():
    result = build_dashboard_suite({})
    assert set(result['dashboards']) == {'portfolio','delivery','schedule','resources','financial','commercial','risk','agile','quality','programme','benefits'}
    assert result['metadata']['posting_policy'].startswith('read-only')


def test_portfolio_dashboard_kpis_and_exceptions():
    result = portfolio_dashboard({'projects': [
        {'status':'In Progress','health':'Red','is_overdue':True},
        {'status':'Completed','health':'Green'}],
        'project_positions': [
            {'project':'P1','currency':'NGN','approved_budget':'100','actual_cost':'60','open_commitments':'20'},
            {'project':'P2','currency':'NGN','approved_budget':'50','actual_cost':'40','open_commitments':'0'}]})
    assert result['kpis']['projects'] == 2
    assert result['kpis']['available_budget'] == Decimal('30')
    assert len(result['exceptions']) == 1


def test_delivery_dashboard_tracks_overdue_and_blocked():
    result = delivery_dashboard({'tasks':[{'status':'Blocked'},{'status':'Completed','is_overdue':True}], 'milestones':[{'is_overdue':True}]})
    assert result['kpis']['blocked_tasks'] == 1
    assert result['kpis']['overdue_tasks'] == 1
    assert result['kpis']['overdue_milestones'] == 1


def test_schedule_dashboard_critical_path_and_variance():
    result = schedule_dashboard({'tasks':[{'is_critical':True,'total_float_days':0}], 'baseline_variances':[{'variance_days':5,'variance_band':'Late'}]})
    assert result['kpis']['critical_activities'] == 1
    assert result['kpis']['average_schedule_variance_days'] == Decimal('5')


def test_resource_dashboard_utilisation():
    result = resource_dashboard({'resources':[{'available_hours':100,'allocated_hours':80}], 'allocations':[{'is_conflict':True}], 'timesheets':[{'status':'Submitted'}]})
    assert result['kpis']['utilisation_percent'] == Decimal('80')
    assert result['kpis']['pending_timesheets'] == 1


def test_financial_dashboard_never_aggregates_mixed_currency():
    result = financial_dashboard({'project_positions':[
        {'currency':'NGN','approved_budget':100,'estimate_at_completion':90},
        {'currency':'USD','approved_budget':10,'estimate_at_completion':8}]})
    assert result['portfolio_totals'] is None
    assert set(result['currency_groups']) == {'NGN','USD'}


def test_commercial_dashboard_exposes_contract_and_claim_exceptions():
    result = commercial_dashboard({'contracts':[{'currency':'NGN','revised_contract_value':500,'retention_held':20,'advance_balance':0}], 'claims':[{'status':'Disputed','is_disputed':True}], 'variations':[{'status':'Pending'}], 'billing_milestones':[{'status':'Ready'}]})
    assert result['kpis']['open_claims'] == 1
    assert result['kpis']['unapproved_variations'] == 1
    assert result['kpis']['retention_held'] == Decimal('20')


def test_risk_agile_and_quality_dashboard_indicators():
    assert risk_dashboard({'risks':[{'rating':'Critical'}], 'issues':[{'status':'Open'}]})['kpis']['critical_risks'] == 1
    assert agile_dashboard({'sprints':[{'status':'Active'}], 'stories':[{'status':'Blocked','story_points':3}]})['kpis']['blocked_stories'] == 1
    assert quality_dashboard({'inspections':[{'result':'Failed'}], 'defects':[{'status':'Open','severity':'Major'}]})['kpis']['failed_inspections'] == 1


def test_dashboard_input_validation():
    with pytest.raises(ValueError):
        build_dashboard_suite([])
    with pytest.raises(ValueError):
        portfolio_dashboard({'projects': {}})
    with pytest.raises(ValueError):
        portfolio_dashboard({'projects':[{'approved_budget':'not-money'}]})


def test_dashboard_page_is_registered_for_desk_navigation():
    import json
    from pathlib import Path
    page = json.loads(Path('velora_projectone/projectone/page/projectone_dashboards/projectone_dashboards.json').read_text())
    assert page['name'] == 'projectone-dashboards'
    assert page['doctype'] == 'Page'


def test_portfolio_dashboard_keeps_mixed_currency_financials_separate():
    result = portfolio_dashboard({
        'projects': [{'status':'In Progress'}, {'status':'Completed'}],
        'project_positions': [
            {'project':'P1','currency':'NGN','approved_budget':100,'actual_cost':40,'open_commitments':10,'estimate_at_completion':60},
            {'project':'P2','currency':'USD','approved_budget':20,'actual_cost':5,'open_commitments':3,'estimate_at_completion':10},
        ]
    })
    assert 'approved_budget' not in result['kpis']
    assert set(result['currency_groups']) == {'NGN','USD'}
    assert result['currency_groups']['NGN']['available_budget'] == Decimal('50')


def test_commercial_dashboard_does_not_add_contract_values_across_currencies():
    result = commercial_dashboard({'contracts': [
        {'currency':'NGN','revised_contract_value':100},
        {'currency':'USD','revised_contract_value':20},
    ]})
    assert 'contract_value' not in result['kpis']
    assert set(result['currency_groups']) == {'NGN','USD'}
