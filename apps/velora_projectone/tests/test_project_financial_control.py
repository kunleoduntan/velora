import pytest
from decimal import Decimal
from velora_projectone.projectone.services.project_financial_control import (
    validate_budget_version, transition_budget, validate_budget_allocation,
    validate_budget_change, transition_budget_change, validate_posted_actual,
    aggregate_actual_costs, project_financial_forecast, category_cost_control,
    portfolio_financial_rollup, validate_revenue_forecast,
)


def budget(**kw):
    return {"project":"PRJ-1","currency":"NGN","budget_version":1,
            "effective_from":"2026-01-01","approved_amount":1000000,"contingency_amount":50000,
            "approval_status":"Draft","created_by":"maker",**kw}


def test_budget_version_validation_and_unique_version():
    assert validate_budget_version(budget())["valid"]
    with pytest.raises(ValueError,match="already exists"):
        validate_budget_version(budget(),[budget()])
    with pytest.raises(ValueError,match="same currency"):
        validate_budget_version(budget(currency="USD",budget_version=2),[budget()])


def test_approved_budget_requires_independent_approval_and_reference():
    with pytest.raises(ValueError,match="authenticated approver"):
        transition_budget({**budget(),"approval_status":"Pending Approval"},"Approved",actor_id=None,approval_reference=None)
    with pytest.raises(ValueError,match="cannot approve"):
        transition_budget({**budget(),"approval_status":"Pending Approval"},"Approved",actor_id="maker",approval_reference="A1")
    approved=transition_budget({**budget(),"approval_status":"Pending Approval"},"Approved",actor_id="approver",approval_reference="A1")
    assert approved["approval_status"]=="Approved"


def test_approved_budget_can_only_be_superseded_by_referenced_new_version():
    approved={**budget(),"approval_status":"Approved","approved_by":"approver","approval_reference":"A1"}
    with pytest.raises(ValueError,match="replacement budget"):
        transition_budget(approved,"Superseded",actor_id="approver")
    assert transition_budget(approved,"Superseded",actor_id="approver",superseding_version="BUD-2")["superseded_by"]=="BUD-2"


def test_budget_line_total_cannot_exceed_approved_authority():
    b=budget()
    lines=[{"cost_category":"LABOUR","period":"2026-01-01","budget_amount":600000},
           {"cost_category":"MATERIAL","period":"2026-01-01","budget_amount":300000}]
    assert validate_budget_allocation(b,lines)["unallocated_amount"]==100000
    with pytest.raises(ValueError,match="exceed"):
        validate_budget_allocation(b,lines+[ {"cost_category":"OTHER","budget_amount":200000} ])


def test_budget_change_pending_does_not_change_authority_until_approved():
    change={"change_id":"BC-1","project":"PRJ-1","change_type":"Increase",
            "currency":"NGN","amount":100000,"reason_code":"Scope Change","justification":"Approved scope expansion","created_by":"maker"}
    assert validate_budget_change(change)["affects_budget_authority"] is False
    pending=transition_budget_change({**change,"status":"Pending Approval"},"Approved",actor_id="approver",approval_reference="APR-1")
    assert validate_budget_change(pending)["affects_budget_authority"] is True
    with pytest.raises(ValueError,match="cannot approve"):
        transition_budget_change({**change,"status":"Pending Approval"},"Approved",actor_id="maker",approval_reference="APR-1")


def actual(**kw):
    return {"project":"PRJ-1","source_doctype":"Purchase Invoice",
            "source_name":"PINV-1","source_line":"1","posting_reference":"JV-1",
            "posting_date":"2026-02-01","currency":"NGN","cost_category":"MATERIAL",
            "amount":25000,"source_status":"Posted",**kw}


def test_actual_import_only_accepts_posted_unique_source_lines():
    assert validate_posted_actual(actual())["read_only_mirror"] is True
    with pytest.raises(ValueError,match="Only posted"):
        validate_posted_actual(actual(source_status="Draft"))
    key=("Purchase Invoice","PINV-1","1")
    with pytest.raises(ValueError,match="already been imported"):
        validate_posted_actual(actual(),[key])


def test_actual_aggregation_filters_project_date_and_duplicates():
    rows=[actual(),actual(source_name="PINV-2",source_line="1",amount=5000),
          actual(source_name="PINV-3",posting_date="2026-03-01",amount=7000)]
    result=aggregate_actual_costs(rows,project="PRJ-1",currency="NGN",as_at="2026-02-28")
    assert result["actual_cost"]==30000
    assert result["by_category"]["MATERIAL"]==30000
    with pytest.raises(ValueError,match="Duplicate"):
        aggregate_actual_costs([actual(),actual()],project="PRJ-1",currency="NGN")


def test_actual_aggregation_rejects_mixed_currencies():
    with pytest.raises(ValueError,match="currency mismatch"):
        aggregate_actual_costs([actual(),actual(source_name="PINV-2",currency="USD")],project="PRJ-1",currency="NGN")


def test_forecast_excludes_pending_changes_and_calculates_margin():
    result=project_financial_forecast(approved_budget=1000,actual_cost=400,open_commitments=100,
        estimate_to_complete=300,approved_budget_changes=50,pending_budget_changes=200,
        recognised_revenue=700,forecast_revenue=1200,currency="NGN")
    assert result["estimate_at_completion"]==800
    assert result["revised_budget"]==1050
    assert result["forecast_variance"]==250
    assert result["pending_budget_changes_excluded"]==200
    assert result["forecast_project_margin"]==400
    assert result["ledger_write_permitted"] is False


def test_category_cost_control_returns_category_variance():
    rows=category_cost_control([{"cost_category":"LABOUR","budget_amount":100}],
        [{"cost_category":"LABOUR","amount":30}],
        [{"cost_category":"LABOUR","open_amount":20}],
        [{"cost_category":"LABOUR","estimate_to_complete":40}])
    assert rows[0]["estimate_at_completion"]==90
    assert rows[0]["variance_at_completion"]==10


def test_portfolio_rollup_groups_currencies_without_fx_conversion():
    result=portfolio_financial_rollup([
        {"currency":"NGN","approved_budget":100,"actual_cost":20,"open_commitments":10,"estimate_at_completion":70,"recognised_revenue":90},
        {"currency":"USD","approved_budget":50,"actual_cost":10,"open_commitments":5,"estimate_at_completion":40,"recognised_revenue":60}])
    assert set(result["currencies"])=={"NGN","USD"}
    assert result["currency_conversion_performed"] is False


def test_project_finance_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app=FastAPI(); install_routes(app,None,lambda request,operation: operation())
    paths={r.path for r in app.routes}
    expected={"/api/projectone/finance/budget/validate-version","/api/projectone/finance/budget/validate-allocation",
      "/api/projectone/finance/budget-change/validate","/api/projectone/finance/actual/validate-source",
      "/api/projectone/finance/actuals/aggregate","/api/projectone/finance/revenue/forecast/validate",
      "/api/projectone/finance/revenue/validate-source","/api/projectone/finance/revenue/aggregate","/api/projectone/finance/forecast/project",
      "/api/projectone/finance/control/by-category","/api/projectone/finance/portfolio-rollup"}
    assert expected.issubset(paths)


def test_budget_transfer_changes_allocation_not_total_authority():
    transfer={"change_id":"BC-T","project":"PRJ-1","change_type":"Transfer",
        "currency":"NGN","amount":25000,"from_cost_category":"LABOUR","to_cost_category":"MATERIAL",
        "justification":"Move unspent funds","status":"Approved","approved_by":"approver","approval_reference":"APR-T"}
    result=validate_budget_change(transfer)
    assert result["authority_delta"]==0
    assert result["reallocation_only"] is True


def revenue(**kw):
    return {"project":"PRJ-1","source_doctype":"Sales Invoice",
        "source_name":"SINV-1","source_line":"1","posting_reference":"JV-REV-1",
        "posting_date":"2026-02-15","currency":"NGN","amount":90000,"source_status":"Posted",**kw}


def test_revenue_forecast_weighted_value_and_probability_bounds():
    row={"project":"PRJ-1","period":"2026-03-01","currency":"NGN","planned_revenue":100000,"probability_percent":75}
    assert validate_revenue_forecast(row)["weighted_forecast_revenue"]==75000
    with pytest.raises(ValueError,match="cannot exceed"):
        validate_revenue_forecast({**row,"probability_percent":120})


def test_recognised_revenue_only_from_posted_unique_source():
    from velora_projectone.projectone.services.project_financial_control import validate_posted_revenue, aggregate_recognised_revenue
    assert validate_posted_revenue(revenue())["recognition_authority"]=="source_application"
    with pytest.raises(ValueError,match="Only posted"):
        validate_posted_revenue(revenue(source_status="Draft"))
    key=("Sales Invoice","SINV-1","1")
    with pytest.raises(ValueError,match="already been imported"):
        validate_posted_revenue(revenue(),[key])
    total=aggregate_recognised_revenue([revenue(),revenue(source_name="SINV-2",amount=10000)],project="PRJ-1",currency="NGN")
    assert total["recognised_revenue"]==100000


def test_recognised_revenue_aggregation_rejects_duplicates_and_currency_mismatch():
    from velora_projectone.projectone.services.project_financial_control import aggregate_recognised_revenue
    with pytest.raises(ValueError,match="Duplicate"):
        aggregate_recognised_revenue([revenue(),revenue()],project="PRJ-1",currency="NGN")
    with pytest.raises(ValueError,match="currency mismatch"):
        aggregate_recognised_revenue([revenue(currency="USD")],project="PRJ-1",currency="NGN")


def test_approved_budget_decrease_is_signed_and_cannot_make_authority_negative():
    result=project_financial_forecast(approved_budget=1000,actual_cost=100,open_commitments=100,
        estimate_to_complete=300,approved_budget_changes=-150)
    assert result["revised_budget"]==850
    with pytest.raises(ValueError,match="below zero"):
        project_financial_forecast(approved_budget=100,actual_cost=0,open_commitments=0,
            estimate_to_complete=0,approved_budget_changes=-101)


def test_budget_lines_must_match_budget_currency():
    with pytest.raises(ValueError,match="currency must match"):
        validate_budget_allocation(budget(),[{"cost_category":"LABOUR","budget_amount":100,"currency":"USD"}])


def test_category_cost_control_rejects_mixed_currency_rows():
    with pytest.raises(ValueError,match="mixed currencies"):
        category_cost_control([], [{"cost_category":"A","amount":10,"currency":"NGN"},
                               {"cost_category":"A","amount":10,"currency":"USD"}], [], [])


def test_financial_snapshot_doctypes_and_workspace_are_present():
    import json
    from pathlib import Path
    package=Path(__file__).resolve().parents[1]/"velora_projectone"
    snapshot=json.loads((package/"projectone/doctype/project_financial_snapshot/project_financial_snapshot.json").read_text())
    assert any(x["fieldname"]=="category_lines" and x["options"]=="Project Financial Category Line" for x in snapshot["fields"])
    workspace=json.loads((package/"projectone/workspace.json").read_text())
    groups={x["label"]:x["items"] for x in workspace["items"] if x.get("type")=="group"}
    assert "Project Financial Snapshot" in groups["Financial Control"]
    assert "Project Cost Actual" in groups["Financial Control"]


def test_cost_to_cost_revenue_recognition_proposes_cumulative_and_current_period_amounts():
    from velora_projectone.projectone.services.project_financial_control import calculate_revenue_recognition
    result = calculate_revenue_recognition(project="PRJ-1", performance_obligation="PO-1",
        currency="NGN", transaction_price=500000, method="cost_to_cost", period_end="2026-06-30",
        cumulative_actual_cost=140000, forecast_total_cost=350000, prior_cumulative_revenue=100000,
        prior_cumulative_cost=70000)
    assert result["progress_percent"] == 40
    assert result["cumulative_revenue"] == 200000
    assert result["current_period_revenue"] == 100000
    assert result["cumulative_profit"] == 60000
    assert result["ledger_write_permitted"] is False
    assert result["approval_status"] == "Pending Review"


def test_revenue_recognition_requires_over_time_or_control_transfer_evidence():
    from velora_projectone.projectone.services.project_financial_control import calculate_revenue_recognition
    base = dict(project="PRJ-1", performance_obligation="PO-1", currency="NGN",
        transaction_price=1000, period_end="2026-06-30")
    with pytest.raises(ValueError, match="over-time"):
        calculate_revenue_recognition(**base, method="output", recognition_over_time=False,
            cumulative_output_units=2, total_output_units=4)
    with pytest.raises(ValueError, match="transfer-of-control"):
        calculate_revenue_recognition(**base, method="point_in_time", recognition_over_time=False)
    confirmed = calculate_revenue_recognition(**base, method="point_in_time", recognition_over_time=False,
        control_transfer_confirmed=True)
    assert confirmed["cumulative_revenue"] == 1000


def test_cost_overrun_is_not_hidden_by_cost_to_cost_progress_cap():
    from velora_projectone.projectone.services.project_financial_control import calculate_revenue_recognition
    result = calculate_revenue_recognition(project="PRJ-1", performance_obligation="PO-1",
        currency="NGN", transaction_price=1000, method="cost_to_cost", period_end="2026-06-30",
        cumulative_actual_cost=1200, forecast_total_cost=1200)
    assert result["progress_percent"] == 100
    assert result["potential_onerous_contract_loss"] is True
    assert result["forecast_total_profit"] == -200


def test_earned_value_metrics_and_zero_denominator_handling():
    from velora_projectone.projectone.services.project_financial_control import calculate_earned_value
    result = calculate_earned_value(planned_value=500, earned_value=400, actual_cost=500, budget_at_completion=1000)
    assert result["cost_variance"] == -100
    assert result["schedule_variance"] == -100
    assert result["cost_performance_index"] == Decimal("0.8")
    assert result["schedule_performance_index"] == Decimal("0.8")
    assert result["estimate_at_completion"] == Decimal("1250")
    assert calculate_earned_value(planned_value=0, earned_value=0, actual_cost=0, budget_at_completion=100)["estimate_at_completion"] is None


def test_profit_recognition_and_earned_value_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI(); install_routes(app, None, lambda request, operation: operation())
    paths = {r.path for r in app.routes}
    assert "/api/projectone/finance/revenue-recognition/calculate" in paths
    assert "/api/projectone/finance/earned-value/calculate" in paths
    assert "/api/projectone/finance/performance-obligation/validate" in paths


def test_recognition_methods_require_their_measurement_inputs():
    from velora_projectone.projectone.services.project_financial_control import calculate_revenue_recognition
    base = dict(project="PRJ-1", performance_obligation="PO-1", currency="NGN",
        transaction_price=1000, period_end="2026-06-30")
    with pytest.raises(ValueError, match="cumulative_output_units"):
        calculate_revenue_recognition(**base, method="output")
    with pytest.raises(ValueError, match="achieved_milestone_value"):
        calculate_revenue_recognition(**base, method="milestone")
    with pytest.raises(ValueError, match="cumulative_progress_percent"):
        calculate_revenue_recognition(**base, method="time_elapsed")


def test_performance_obligation_requires_approved_accounting_basis_and_segregated_approval():
    from velora_projectone.projectone.services.project_financial_control import validate_performance_obligation, transition_performance_obligation
    obligation = {"project":"PRJ-1","contract_reference":"CON-1",
        "obligation_code":"PO-1","description":"Implementation services","currency":"NGN",
        "allocated_transaction_price":500000,"recognition_method":"Cost To Cost",
        "recognition_over_time":True,"accounting_conclusion_reference":"MEMO-001","created_by":"maker"}
    assert validate_performance_obligation(obligation)["valid"]
    pending = transition_performance_obligation({**obligation,"status":"Pending Approval"},"Approved",
        actor_id="finance-approver",approval_reference="FIN-APR-01")
    assert validate_performance_obligation(pending)["immutable_when_approved"]
    with pytest.raises(ValueError, match="cannot approve"):
        transition_performance_obligation({**obligation,"status":"Pending Approval"},"Approved",
            actor_id="maker",approval_reference="FIN-APR-01")
    with pytest.raises(ValueError, match="over-time"):
        validate_performance_obligation({**obligation,"recognition_method":"Cost To Cost","recognition_over_time":False})


def test_revenue_recognition_doctypes_and_workspace_are_registered():
    import json
    from pathlib import Path
    package = Path(__file__).resolve().parents[1] / "velora_projectone"
    obligation = json.loads((package / "projectone/doctype/project_performance_obligation/project_performance_obligation.json").read_text())
    recognition = json.loads((package / "projectone/doctype/project_revenue_recognition/project_revenue_recognition.json").read_text())
    assert obligation["name"] == "Project Performance Obligation"
    assert recognition["name"] == "Project Revenue Recognition"
    assert any(f["fieldname"] == "current_period_profit" for f in recognition["fields"])
    workspace = json.loads((package / "projectone/workspace.json").read_text())
    financial = next(x for x in workspace["items"] if x.get("label") == "Financial Control")
    assert "Project Performance Obligation" in financial["items"]
    assert "Project Revenue Recognition" in financial["items"]


def test_native_finance_workflow_lifecycle_enforces_maker_checker_and_state():
    from velora_projectone.projectone.services.workflow_lifecycle import validate_lifecycle_command
    obligation = {"status":"Pending Approval", "owner":"maker"}
    with pytest.raises(PermissionError, match="requester cannot approve"):
        validate_lifecycle_command("Project Performance Obligation", "approve", obligation, "maker", {"approval_reference":"A1"})
    assert validate_lifecycle_command("Project Performance Obligation", "approve", obligation, "checker", {"approval_reference":"A1"})["validated"]
    recognition = {"approval_status":"Pending Review", "owner":"maker"}
    with pytest.raises(PermissionError, match="requester cannot approve"):
        validate_lifecycle_command("Project Revenue Recognition", "approve", recognition, "maker", {"finance_review_reference":"FIN-1"})
    assert validate_lifecycle_command("Project Revenue Recognition", "approve", recognition, "finance-checker", {"finance_review_reference":"FIN-1"})["validated"]


def test_finance_command_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app=FastAPI(); install_routes(app,None,lambda request,operation: operation())
    paths={r.path for r in app.routes}
    assert "/api/projectone/finance/performance-obligations" in paths
    assert "/api/projectone/finance/performance-obligations/{name}/workflow/{action}" in paths
    assert "/api/projectone/finance/revenue-recognition/proposals" in paths
    assert "/api/projectone/finance/revenue-recognition/{name}/workflow/{action}" in paths
