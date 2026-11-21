import calendar
from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_cash_transactions import setup_cash, approve, MAKER, APPROVER
from velora_erp.finance import budget_planner as bp, budget_control as bc

T = date.today()
D = Decimal


def _row(accounts, **months):
    return {"account": accounts["5000"].name, **months}


def test_year_months_follow_the_financial_year_not_the_calendar():
    m = bp.year_months(date(2026, 7, 1), date(2027, 6, 30))
    assert m["jul"][0] == date(2026, 7, 1) and m["jun"][1] == date(2027, 6, 30) and len(m) == 12
    short = bp.year_months(date(2026, 1, 1), date(2026, 3, 31))
    assert sorted(short) == ["feb", "jan", "mar"]
    with pytest.raises(ValidationError):
        bp.year_months(date(2026, 1, 15), date(2026, 12, 31))


def test_plan_lines_skip_zero_months_and_reject_negative_or_out_of_year():
    lines = bp.plan_to_lines([{"account": "A", "jan": 100, "mar": "50.555", "cost_centre": "CC1"}], date(2026, 1, 1), date(2026, 12, 31),
                             header={"branch": "HQ"})
    assert [l["period_start"] for l in lines] == [date(2026, 1, 1), date(2026, 3, 1)]
    assert lines[1]["budget_amount"] == D("50.56") and lines[0]["cost_centre"] == "CC1" and lines[0]["branch"] == "HQ"
    with pytest.raises(ValidationError, match="negative"):
        bp.plan_to_lines([{"account": "A", "jan": -1}], date(2026, 1, 1), date(2026, 12, 31))
    with pytest.raises(ValidationError, match="outside"):
        bp.plan_to_lines([{"account": "A", "dec": 5}], date(2026, 1, 1), date(2026, 3, 31))


def test_allocation_equal_basis_and_locked_always_total_exactly_100():
    rows = [{"branch": "A"}, {"branch": "B"}, {"branch": "C"}]
    pct = bp.allocation_percentages(rows, "Equal", dimension="branch")
    assert sum(pct) == D("100") and sorted(pct) == [D("33.33"), D("33.33"), D("33.34")]
    basis = [{"branch": "A", "basis_value": 60}, {"branch": "B", "basis_value": 30}, {"branch": "C", "basis_value": 10}]
    assert bp.allocation_percentages(basis, "Proportional to Basis", dimension="branch") == [D("60.00"), D("30.00"), D("10.00")]
    kept = [{"branch": "A", "allocation_percent": 50, "is_locked": 1}, {"branch": "B"}, {"branch": "C"}]
    assert bp.allocation_percentages(kept, "Equal", dimension="branch") == [D("50"), D("25.00"), D("25.00")]
    with pytest.raises(ValidationError, match="not 100"):
        bp.allocation_percentages([{"branch": "A", "allocation_percent": 60}, {"branch": "B", "allocation_percent": 30}], "Custom %", dimension="branch")
    with pytest.raises(ValidationError, match="twice"):
        bp.allocation_percentages([{"branch": "A"}, {"branch": "A"}], "Equal", dimension="branch")
    with pytest.raises(ValidationError, match="more than 100"):
        bp.allocation_percentages([{"branch": "A", "allocation_percent": 120, "is_locked": 1}, {"branch": "B"}], "Equal", dimension="branch")


def test_split_amount_never_loses_a_kobo():
    for amount in ("100.00", "0.01", "1000000.07", "333.33"):
        parts = bp.split_amount(D(amount), [D("33.33"), D("33.33"), D("33.34")])
        assert sum(parts) == D(amount)


def test_allocate_lines_shares_only_unassigned_lines():
    lines = [{"account": "A", "budget_amount": D("100.00"), "branch": None}, {"account": "B", "budget_amount": D("40.00"), "branch": "HQ"}]
    out = bp.allocate_lines(lines, [{"branch": "X"}, {"branch": "Y"}], "Equal", dimension="branch")
    assert sum(l["budget_amount"] for l in out) == D("140.00")
    assert [l["branch"] for l in out if l["account"] == "B"] == ["HQ"]
    assert {l["branch"] for l in out if l["account"] == "A"} == {"X", "Y"}


def test_projection_equal_pattern_and_growth_tie_to_the_total():
    prev = {"jan": 100, "feb": 200, "mar": 300}
    eq = bp.project_months(prev, "Equal Distribution", 10)
    assert sum(eq.values()) == D("660.00") and eq["jan"] == D("55.00")
    pat = bp.project_months(prev, "Historical Pattern", 10)
    assert pat["jan"] == D("110.00") and pat["feb"] == D("220.00") and sum(pat.values()) == D("660.00")
    with pytest.raises(ValidationError):
        bp.project_months(prev, "Guess", 0)


def test_scenarios_price_against_base_and_weight_by_probability():
    out = bp.scenario_rows(1000, [{"scenario_name": "Best", "adjustment_percent": 10, "probability": 25, "is_active": 1},
                                  {"scenario_name": "Worst", "adjustment_percent": -20, "probability": 75, "is_active": 1},
                                  {"scenario_name": "Off", "adjustment_percent": 50, "probability": 100, "is_active": 0}])
    assert out[0]["total_budget"] == 1100 and out[1]["variance_from_base"] == -200 and out[0]["expected_total"] == 875
    with pytest.raises(ValidationError):
        bp.scenario_rows(1000, [{"scenario_name": "x", "adjustment_percent": -100}])


def test_variance_signs_by_account_type_and_projects_year_end(monkeypatch):
    monkeypatch.setattr(bp, "_root_types", lambda accounts: {"EXP": "Expense", "INC": "Income"})
    rows = [{"account": "EXP", "jan": 100, "feb": 100, "mar": 100}, {"account": "INC", "jan": 100, "feb": 100}]
    actuals = {"EXP": {"jan": D("120"), "feb": D("100")}, "INC": {"jan": D("50"), "feb": D("60")}}
    v = {r["account"]: r for r in bp.variance(rows, actuals, through_month=2)}
    assert v["EXP"]["variance"] == -20 and v["EXP"]["better_when"] == "lower" and v["EXP"]["utilisation_percent"] == 110
    assert v["INC"]["variance"] == 90 and v["INC"]["better_when"] == "higher"
    assert v["EXP"]["projected_year_end"] == 1320


def test_default_through_month_clips_to_the_year():
    assert bp.default_through_month(date(2026, 1, 1), date(2026, 12, 31), date(2026, 5, 20)) == 5
    assert bp.default_through_month(date(2026, 1, 1), date(2026, 12, 31), date(2025, 12, 1)) == 0
    assert bp.default_through_month(date(2026, 1, 1), date(2026, 12, 31), date(2027, 3, 1)) == 12
    assert bp.default_through_month(date(2026, 7, 1), date(2027, 6, 30), date(2027, 1, 9)) == 7


def test_budget_document_builds_lines_from_the_plan_and_feeds_budget_control(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            b = new_doc("Financial Budget", budget_name="PLAN", budget_scenario="Original", financial_year=f"FY-{T.year}",
                        account_budgets=[_row(accounts, jan=1000, feb=2000)],
                        scenarios=[{"scenario_name": "Down", "adjustment_percent": -10, "probability": 100}]).insert()
        assert [(str(l.period_start)[:7], float(l.budget_amount)) for l in b.lines] == [(f"{T.year}-01", 1000.0), (f"{T.year}-02", 2000.0)]
        assert float(b.total_budget_amount) == 3000.0 and float(b.account_budgets[0].total) == 3000.0
        assert float(b.scenarios[0].total_budget) == 2700.0 and float(b.scenarios[0].variance_from_base) == -300.0
        with pytest.raises(ValidationError, match="planned twice"):
            with session_as(MAKER):
                new_doc("Financial Budget", budget_name="DUP", budget_scenario="Original", financial_year=f"FY-{T.year}",
                        account_budgets=[_row(accounts, jan=1), _row(accounts, feb=2)]).insert()
    finally:
        velora.shutdown()


def test_budget_shared_across_branches_ties_out_and_group_budgets_do_not_control(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        names = []
        for code in ("HQ", "LAG"):
            names.append(new_doc("Branch", branch_code=code, branch_name=code).insert(ignore_permissions=True).name)
        hq, lag = names
        with session_as(MAKER):
            b = new_doc("Financial Budget", budget_name="SPLIT", budget_scenario="Original", financial_year=f"FY-{T.year}",
                        account_budgets=[_row(accounts, jan=1000.01)], allocate_by="Branch", allocation_method="Custom %",
                        allocations=[{"branch": hq, "allocation_percent": 60}, {"branch": lag, "allocation_percent": 40}]).insert()
        assert sum(float(l.budget_amount) for l in b.lines) == pytest.approx(1000.01) and {l.branch for l in b.lines} == {hq, lag}
        assert [float(a.allocated_amount) for a in b.allocations] == pytest.approx([600.01, 400.0])
        with session_as(MAKER):
            g = new_doc("Financial Budget", budget_name="GROUP", budget_scenario="Original", financial_year=f"FY-{T.year}", is_group_budget=1).insert()
        assert g.lines == [] and g.parent_budget is None
        with session_as(MAKER):
            child = new_doc("Financial Budget", budget_name="CHILD", budget_scenario="Original", financial_year=f"FY-{T.year}",
                            parent_budget=g.name, account_budgets=[_row(accounts, jan=10)]).insert()
            with pytest.raises(ValidationError, match="group"):
                new_doc("Financial Budget", budget_name="BAD", budget_scenario="Original", financial_year=f"FY-{T.year}",
                        parent_budget=child.name, account_budgets=[_row(accounts, jan=10)]).insert()
    finally:
        velora.shutdown()


def test_workbench_compares_plan_with_posted_actuals_and_old_style_budgets_still_work(tmp_path):
    from test_budget_control_v271 import _budget, _expense
    accounts, c, s = setup_cash(tmp_path)
    try:
        old = _budget(accounts, 1000)                       # a budget entered the old way, line by line
        wb = bp.workbench(old.name)
        assert wb["plan"] == [] and wb["total"] == 0 and wb["budget"]["is_group_budget"] is False
        with session_as(MAKER):
            planned = new_doc("Financial Budget", budget_name="WB", budget_scenario="Original", financial_year=f"FY-{T.year}",
                              account_budgets=[_row(accounts, **{bp.MONTHS[T.month - 1]: 500})],
                              scenarios=[{"scenario_name": "Tight", "adjustment_percent": -10, "probability": 100}]).insert()
        _expense(accounts, 120)
        wb = bp.workbench(planned.name, through_month=T.month)
        row = wb["variance"][0]
        assert wb["total"] == 500 and row["budget_to_date"] == 500 and row["actual_to_date"] == 120 and row["variance"] == 380
        assert row["better_when"] == "lower" and wb["actual_months"][bp.MONTHS[T.month - 1]] == 120
        assert wb["scenarios"][0]["total_budget"] == 450 and wb["scenario_months"][0]["months"][bp.MONTHS[T.month - 1]] == 450
        assert bp.workbench(planned.name)["through_month"] >= 1
    finally:
        velora.shutdown()


def test_propose_plan_projects_last_years_activity(tmp_path, monkeypatch):
    accounts, c, s = setup_cash(tmp_path)
    try:
        acc = accounts["5000"].name
        monkeypatch.setattr(bp, "monthly_actuals", lambda accts, a, b, **k: {acc: {"jan": D("100"), "jul": D("300")}})
        rows = bp.propose_plan(f"FY-{T.year}", method="Historical Pattern", growth_percent=10)
        mine = [r for r in rows if r["account"] == acc]
        assert mine and mine[0]["jan"] == 110.0 and mine[0]["jul"] == 330.0 and mine[0]["total"] == 440.0
        out = bp.project_rows(f"FY-{T.year}", [{"account": acc}], method="Equal Distribution", growth_percent=0)
        assert sum(out[0][m] for m in bp.MONTHS) == 400.0 and out[0]["previous_year_actual"] == 400.0
    finally:
        velora.shutdown()
