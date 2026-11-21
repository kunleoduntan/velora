from decimal import Decimal
import pytest
from velora_erp.finance.reporting.budget_forecast import build_budget_variance, build_rolling_forecast, BudgetForecastError
from velora_erp.finance.reporting.cash_flow_intelligence import build_cash_forecast, build_liquidity_runway, CashFlowIntelligenceError
from velora_erp.finance.reporting.executive_reporting import build_executive_scorecard, ExecutiveReportingError


def test_budget_variance_and_favourability_policy():
    a=[{"entity":"E1","currency":"NGN","period":"2026-01","values":{"revenue":"120","cost":"55"}}]
    b=[{"entity":"E1","currency":"NGN","period":"2026-01","values":{"revenue":"100","cost":"60"}}]
    r=build_budget_variance(a,b,favourable_metrics={"cost"},higher_is_favourable={"revenue"})
    m=r["periods"][0]["metrics"]
    assert m["revenue"]["variance"] == Decimal("20") and m["revenue"]["favourability"] == "favourable"
    assert m["cost"]["variance"] == Decimal("-5") and m["cost"]["favourability"] == "favourable"


def test_budget_mismatched_entity_rejected():
    a=[{"entity":"E1","currency":"NGN","period":"P1","values":{"x":1}}]
    b=[{"entity":"E2","currency":"NGN","period":"P1","values":{"x":1}}]
    with pytest.raises(BudgetForecastError): build_budget_variance(a,b)


def test_rolling_forecast_requires_opening_and_rolls_forward():
    rows=[{"entity":"E1","currency":"NGN","period":"P1","opening_balance":"100","net_movement":"25"},
          {"entity":"E1","currency":"NGN","period":"P2","net_movement":"-10"}]
    r=build_rolling_forecast(rows)
    assert r["periods"][1]["closing_balance"] == Decimal("115")
    with pytest.raises(BudgetForecastError): build_rolling_forecast([{**rows[0],"opening_balance":None}])


def test_cash_forecast_flags_liquidity_floor():
    rows=[{"entity":"E1","currency":"NGN","period":"P1","opening_cash":"100","inflows":"20","outflows":"30"},
          {"entity":"E1","currency":"NGN","period":"P2","inflows":"5","outflows":"50"}]
    r=build_cash_forecast(rows,minimum_liquidity="60")
    assert r["risk_periods"] == ["P2"]
    assert r["periods"][1]["closing_cash"] == Decimal("45")


def test_cash_forecast_rejects_negative_inflows():
    rows=[{"entity":"E1","currency":"NGN","period":"P1","opening_cash":1,"inflows":-1,"outflows":0}]
    with pytest.raises(CashFlowIntelligenceError): build_cash_forecast(rows)


def test_liquidity_runway_zero_burn_is_not_infinite():
    assert build_liquidity_runway("100", "0")["runway_days"] is None
    assert build_liquidity_runway("100", "5")["runway_days"] == Decimal("20")


def test_executive_scorecard_preserves_sources_and_blocks_mismatched_cash():
    cash=build_cash_forecast([{"entity":"E1","currency":"NGN","period":"P1","opening_cash":100,"inflows":0,"outflows":0}])
    r=build_executive_scorecard(entity="E1",currency="NGN",period="FY26",
        financial_metrics={"revenue":{"value":"1000","source_refs":["GL:REV"]}},
        cash_forecast=cash,materiality_thresholds={"revenue":"900"})
    assert r["financial_metrics"]["revenue"]["source_refs"] == ["GL:REV"]
    assert r["materiality_flags"][0]["metric"] == "revenue"
    with pytest.raises(ExecutiveReportingError):
        build_executive_scorecard(entity="E1",currency="NGN",period="FY26",financial_metrics={},
            cash_forecast={"entity":"E2","currency":"NGN","periods":[]})
