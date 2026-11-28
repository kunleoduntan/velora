from decimal import Decimal
import pytest
from velora_projectone.projectone.reports.dashboard_intelligence import (
    filter_dashboard_data, dashboard_drilldown, trend_series,
    validate_dashboard_view, build_dashboard_snapshot,
)


def test_filters_apply_project_status_and_date_without_mutating_source():
    source = {'tasks': [
        {'project_id': 'P1', 'status': 'Open', 'due_date': '2026-01-10'},
        {'project_id': 'P2', 'status': 'Open', 'due_date': '2026-01-10'},
        {'project_id': 'P1', 'status': 'Done', 'due_date': '2026-02-10'},
    ]}
    result = filter_dashboard_data(source, {'project_id': 'P1', 'status': 'Open', 'start_date': '2026-01-01', 'end_date': '2026-01-31'})
    assert len(result['tasks']) == 1
    assert len(source['tasks']) == 3


def test_filter_rejects_unknown_keys_bad_dates_and_reversed_ranges():
    with pytest.raises(ValueError): filter_dashboard_data({}, {'company': 'C1'})
    with pytest.raises(ValueError): filter_dashboard_data({}, {'start_date': 'yesterday'})
    with pytest.raises(ValueError): filter_dashboard_data({}, {'start_date': '2026-02-01', 'end_date': '2026-01-01'})


def test_drilldown_is_allowlisted_and_paginated():
    rows = [{'project_id': 'P1', 'name': str(i)} for i in range(8)]
    result = dashboard_drilldown({'tasks': rows}, 'delivery', 'tasks', {'project_id': 'P1'}, limit=3, offset=3)
    assert result['total'] == 8 and [r['name'] for r in result['rows']] == ['3', '4', '5']
    with pytest.raises(ValueError): dashboard_drilldown({}, 'delivery', 'users')
    with pytest.raises(ValueError): dashboard_drilldown({}, 'delivery', 'tasks', limit=501)


def test_monthly_trends_keep_currencies_separate():
    result = trend_series([
        {'posting_date': '2026-01-05', 'amount': '10', 'currency': 'NGN'},
        {'posting_date': '2026-01-20', 'amount': '5', 'currency': 'NGN'},
        {'posting_date': '2026-01-20', 'amount': '7', 'currency': 'USD'},
    ])
    assert result['currency_series']['NGN'][0]['value'] == Decimal('15')
    assert result['currency_series']['USD'][0]['value'] == Decimal('7')
    assert len(result['currency_series']) == 2


def test_dashboard_view_validates_unique_widgets_and_allowlisted_filters():
    view = {'name': 'PMO View', 'dashboard': 'portfolio', 'widgets': [
        {'id': 'health', 'visible': True, 'order': 1, 'width': 2}], 'filters': {'status': 'Active'}}
    assert validate_dashboard_view(view)['valid'] is True
    with pytest.raises(ValueError): validate_dashboard_view({**view, 'widgets': [{'id': 'x'}, {'id': 'x'}]})
    with pytest.raises(ValueError): validate_dashboard_view({**view, 'filters': {'company': 'C1'}})


def test_snapshot_requires_trusted_scope_and_marks_immutable_read_model():
    payload = {'kpis': {'projects': 4}}
    snap = build_dashboard_snapshot('portfolio', payload, generated_at='2026-11-21T07:00:00+01:00', company_scope='COMP-001')
    assert snap['metadata']['immutable_snapshot'] is True
    with pytest.raises(ValueError): build_dashboard_snapshot('portfolio', payload, generated_at='now', company_scope='')


def test_dashboard_intelligence_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, operation: operation())
    paths = {route.path for route in app.routes}
    assert '/api/projectone/dashboards/{dashboard_name}/drilldown' in paths
    assert '/api/projectone/dashboards/trends/monthly' in paths
    assert '/api/projectone/dashboards/views/validate' in paths
    assert '/api/projectone/dashboards/snapshots/preview' in paths
