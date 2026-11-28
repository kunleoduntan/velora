import pytest
from velora_projectone.projectone.reports.executive_workspace import build_executive_workspace


def test_executive_workspace_groups_finance_by_currency_and_uses_position_over_detail():
    result = build_executive_workspace({
        "company_scope": "COMP-1", "project_scope": None,
        "data": {
            "project_positions": [{"name":"P1","project_id":"P1","currency":"NGN","approved_budget":1000,"actual_cost":300,"open_commitments":100}],
            "cost_actuals": [{"name":"C1","project_id":"P1","currency":"NGN","amount":300}],
            "commitments": [{"name":"PO1","project_id":"P1","currency":"NGN","amount":100}],
            "recognised_revenue": [{"name":"R1","project_id":"P1","currency":"USD","amount":50}],
        },
        "provenance": {"accounting":{"status":"connected","records":3,"collections":["project_positions"],"read_only":True}}
    })
    ngn = next(x for x in result["financial_by_currency"] if x["currency"] == "NGN")
    assert ngn["actual_cost"] == 300
    assert ngn["open_commitments"] == 100
    assert ngn["available_budget"] == 600
    assert {x["currency"] for x in result["financial_by_currency"]} == {"NGN", "USD"}
    assert result["metadata"]["read_only"] is True


def test_executive_workspace_reports_missing_currency_and_project_link():
    result = build_executive_workspace({"data":{"cost_actuals":[{"name":"C1","amount":25}]},"provenance":{}})
    codes = {x["code"] for x in result["data_quality"]["issues"]}
    assert "MISSING_CURRENCY" in codes
    assert "MISSING_PROJECT" in codes


def test_executive_workspace_rejects_invalid_money():
    with pytest.raises(ValueError):
        build_executive_workspace({"data":{"project_positions":[{"currency":"NGN","approved_budget":"NaN"}]},"provenance":{}})


def test_executive_workspace_distinguishes_unconfigured_source():
    result = build_executive_workspace({"data":{},"provenance":{"hrms":{"status":"not_configured","collections":[]}}})
    assert result["source_health"]["connected_count"] == 0
    assert result["source_health"]["sources"]["hrms"]["status"] == "not_configured"


def test_executive_workspace_route_is_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, callback: callback())
    paths = {route.path for route in app.routes}
    assert "/api/projectone/portfolio/executive-workspace" in paths
