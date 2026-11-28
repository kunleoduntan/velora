"""Dashboard filtering, drill-down, trend and saved-view validation.

The host must supply authenticated, company/row-policy-filtered source rows.
This module is a deterministic read-model layer; persistence of saved views and
snapshots is delegated to the host repository.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

COLLECTIONS = {
    "projects", "tasks", "dependencies", "milestones", "baseline_variances", "resources",
    "allocations", "timesheets", "project_positions", "contracts", "claims",
    "variations", "billing_milestones", "risks", "issues", "change_requests",
    "sprints", "stories", "inspections", "deliverables", "defects",
    "portfolios", "programmes", "benefits", "budgets",
}
DATE_FIELDS = ("posting_date", "transaction_date", "date", "start_date", "due_date", "planned_date", "actual_date", "period_start")


def _date(value, field):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD).")


def filter_dashboard_data(data, filters=None):
    """Apply safe, explicit filters to already-authorised rows only."""
    if not isinstance(data, dict):
        raise ValueError("Dashboard data must be an object.")
    filters = filters or {}
    if not isinstance(filters, dict):
        raise ValueError("Dashboard filters must be an object.")
    allowed = {"project_id", "portfolio_id", "programme_id", "status", "start_date", "end_date", "as_at"}
    unknown = set(filters) - allowed
    if unknown:
        raise ValueError(f"Unsupported dashboard filters: {', '.join(sorted(unknown))}.")
    start = _date(filters.get("start_date"), "start_date")
    end = _date(filters.get("end_date"), "end_date")
    as_at = _date(filters.get("as_at"), "as_at")
    if start and end and start > end:
        raise ValueError("start_date cannot be later than end_date.")
    result = dict(data)
    for collection in COLLECTIONS:
        rows = data.get(collection)
        if rows is None:
            continue
        if not isinstance(rows, list):
            raise ValueError(f"{collection} must be a list.")
        selected = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Every {collection} row must be an object.")
            if filters.get("project_id") and str(row.get("project_id")) != str(filters["project_id"]):
                continue
            if filters.get("portfolio_id") and str(row.get("portfolio_id")) != str(filters["portfolio_id"]):
                continue
            if filters.get("programme_id") and str(row.get("programme_id")) != str(filters["programme_id"]):
                continue
            if filters.get("status") and str(row.get("status")) != str(filters["status"]):
                continue
            row_date = None
            for field in DATE_FIELDS:
                if row.get(field):
                    row_date = _date(row[field], field)
                    break
            if start and row_date and row_date < start:
                continue
            if end and row_date and row_date > end:
                continue
            if as_at and row_date and row_date > as_at:
                continue
            selected.append(row)
        result[collection] = selected
    return result


def dashboard_drilldown(data, dashboard_name, collection, filters=None, limit=100, offset=0):
    """Return a paginated detail list from a permission-filtered collection."""
    if collection not in COLLECTIONS:
        raise ValueError("Unsupported drill-down collection.")
    if dashboard_name not in {"portfolio", "delivery", "schedule", "resources", "financial", "commercial", "risk", "agile", "quality", "programme", "benefits"}:
        raise ValueError("Unknown dashboard.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500.")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be a non-negative integer.")
    rows = filter_dashboard_data(data, filters).get(collection, [])
    return {"dashboard": dashboard_name, "collection": collection, "total": len(rows),
            "limit": limit, "offset": offset, "rows": rows[offset:offset + limit],
            "metadata": {"data_scope": "host-permission-filtered", "read_only": True}}


def trend_series(rows, *, date_field="posting_date", value_field="amount", currency_field="currency"):
    """Monthly trend grouped by currency, never combining unlike currencies."""
    if not isinstance(rows, list):
        raise ValueError("Trend rows must be a list.")
    grouped = defaultdict(Decimal)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Every trend row must be an object.")
        dt = _date(row.get(date_field), date_field)
        if dt is None:
            continue
        try:
            amount = Decimal(str(row.get(value_field, 0) or 0))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"{value_field} must be numeric.")
        if not amount.is_finite():
            raise ValueError(f"{value_field} must be finite.")
        currency = str(row.get(currency_field) or "UNSPECIFIED")
        grouped[(currency, dt.strftime("%Y-%m"))] += amount
    currencies = sorted({k[0] for k in grouped})
    return {"currency_series": {currency: [{"period": period, "value": grouped[(currency, period)]}
            for period in sorted(p for c, p in grouped if c == currency)] for currency in currencies},
            "currency_policy": "separate-series; no implicit FX conversion"}


def validate_dashboard_view(view):
    """Validate user layout preferences before host persistence."""
    if not isinstance(view, dict):
        raise ValueError("Dashboard view must be an object.")
    allowed = {"name", "dashboard", "widgets", "filters", "is_default"}
    if set(view) - allowed:
        raise ValueError("Dashboard view contains unsupported fields.")
    if not str(view.get("name") or "").strip() or len(str(view["name"])) > 120:
        raise ValueError("Dashboard view name is required and must not exceed 120 characters.")
    if view.get("dashboard") not in {"portfolio", "delivery", "schedule", "resources", "financial", "commercial", "risk", "agile", "quality", "programme", "benefits"}:
        raise ValueError("Dashboard view references an unknown dashboard.")
    widgets = view.get("widgets", [])
    if not isinstance(widgets, list) or len(widgets) > 40:
        raise ValueError("widgets must be a list of at most 40 entries.")
    seen = set()
    for widget in widgets:
        if not isinstance(widget, dict) or set(widget) - {"id", "visible", "order", "width"}:
            raise ValueError("Invalid dashboard widget configuration.")
        wid = str(widget.get("id") or "")
        if not wid or wid in seen:
            raise ValueError("Dashboard widget IDs must be non-empty and unique.")
        seen.add(wid)
        if widget.get("width", 1) not in (1, 2, 3, 4):
            raise ValueError("Widget width must be between 1 and 4.")
        if not isinstance(widget.get("order", 0), int) or isinstance(widget.get("order", 0), bool):
            raise ValueError("Widget order must be an integer.")
    filters = view.get("filters", {})
    if not isinstance(filters, dict) or set(filters) - {"project_id", "portfolio_id", "programme_id", "status", "start_date", "end_date", "as_at"}:
        raise ValueError("Dashboard view contains unsupported filters.")
    return {"valid": True, "view": view, "persistence": "host-repository-required"}


def build_dashboard_snapshot(dashboard_name, payload, *, generated_at, company_scope):
    """Create a serialisable snapshot envelope; does not persist it."""
    if dashboard_name not in {"portfolio", "delivery", "schedule", "resources", "financial", "commercial", "risk", "agile", "quality", "programme", "benefits"}:
        raise ValueError("Unknown dashboard.")
    if not isinstance(payload, dict) or not isinstance(payload.get("kpis", {}), dict):
        raise ValueError("Dashboard payload is invalid.")
    if not generated_at or not company_scope:
        raise ValueError("generated_at and trusted company_scope are required.")
    return {"dashboard": dashboard_name, "generated_at": str(generated_at),
            "company_scope": str(company_scope), "payload": payload,
            "metadata": {"immutable_snapshot": True, "read_only": True,
                         "source_scope": "host-authenticated-company-and-row-policy"}}
