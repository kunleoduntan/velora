"""Project finance read models and source-commitment reconciliation.

This module never creates ledger entries. Source systems remain authoritative;
these functions produce project control calculations only.
"""
from decimal import Decimal, InvalidOperation


def _money(value, field):
    try: amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError): raise ValueError(f"{field} must be numeric.")
    if not amount.is_finite() or amount < 0: raise ValueError(f"{field} must be finite and non-negative.")
    return amount


def reconcile_commitment(source_order_amount, invoiced_against_order, cancelled_amount=0):
    order = _money(source_order_amount, "source_order_amount")
    invoiced = _money(invoiced_against_order, "invoiced_against_order")
    cancelled = _money(cancelled_amount, "cancelled_amount")
    if invoiced + cancelled > order:
        raise ValueError("Invoiced plus cancelled value cannot exceed the source commitment.")
    return {"source_amount": order, "invoiced_amount": invoiced, "cancelled_amount": cancelled,
            "open_commitment": order-invoiced-cancelled, "reconciled": True}


def calculate_project_financial_position(approved_budget, actual_cost, open_commitments,
                                          recognised_revenue=0, forecast_cost_at_completion=None):
    budget = _money(approved_budget, "approved_budget")
    actual = _money(actual_cost, "actual_cost")
    commitments = _money(open_commitments, "open_commitments")
    revenue = _money(recognised_revenue, "recognised_revenue")
    exposure = actual + commitments
    forecast = _money(forecast_cost_at_completion, "forecast_cost_at_completion") if forecast_cost_at_completion is not None else exposure
    return {"approved_budget": budget, "actual_cost": actual, "open_commitments": commitments,
            "total_exposure": exposure, "available_budget": budget-exposure,
            "recognised_revenue": revenue, "forecast_cost_at_completion": forecast,
            "forecast_budget_variance": budget-forecast,
            "forecast_project_margin": revenue-forecast}


def validate_source_reference(source_doctype, source_name, project, amount, currency):
    required = {"source_doctype": source_doctype, "source_name": source_name,
                "project": project, "currency": currency}
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    if missing: raise ValueError("Missing source reference fields: " + ", ".join(missing))
    amount = _money(amount, "amount")
    return {**required, "amount": amount, "posting_authority": "source_application",
            "ledger_write_permitted": False}
