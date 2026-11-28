"""Executive portfolio workspace built only from host-authorised source reads.

This module is a read-model aggregator. It never writes upstream records and
never converts currencies implicitly. Source provenance and data-quality
exceptions are first-class output so executives can distinguish zero from
missing or unconnected data.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, InvalidOperation


def _number(value, field):
    try:
        result = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric.")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite.")
    return result


def build_executive_workspace(integration_result: dict) -> dict:
    """Build a multi-currency executive view and data-quality register.

    Expected input is the envelope returned by ProjectOneReadIntegration,
    not arbitrary client-provided data. Deployment must call this only after
    trusted actor authentication and source permission checks.
    """
    if not isinstance(integration_result, dict):
        raise ValueError("Integration result must be an object.")
    data = integration_result.get("data", {})
    provenance = integration_result.get("provenance", {})
    if not isinstance(data, dict) or not isinstance(provenance, dict):
        raise ValueError("Integration data and provenance must be objects.")

    quality = []
    counts = {}
    for collection, rows in sorted(data.items()):
        if not isinstance(rows, list):
            raise ValueError(f"{collection} must be a list.")
        counts[collection] = len(rows)
        seen = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                quality.append({"collection": collection, "row": index, "severity": "High", "code": "INVALID_ROW", "message": "Source row is not an object."})
                continue
            identifier = row.get("name") or row.get("source_name") or row.get("id")
            if identifier is None:
                quality.append({"collection": collection, "row": index, "severity": "Medium", "code": "MISSING_IDENTIFIER", "message": "Source row has no stable identifier."})
            elif str(identifier) in seen:
                quality.append({"collection": collection, "row": index, "severity": "High", "code": "DUPLICATE_IDENTIFIER", "message": "Duplicate source identifier in collection."})
            else:
                seen.add(str(identifier))
            if not row.get("project_id"):
                quality.append({"collection": collection, "row": index, "severity": "Medium", "code": "MISSING_PROJECT", "message": "Source row is not linked to a ProjectOne project."})

    for collection in ("project_positions", "cost_actuals", "commitments", "recognised_revenue"):
        for index, row in enumerate(data.get(collection, [])):
            if isinstance(row, dict) and not str(row.get("currency") or "").strip():
                quality.append({"collection": collection, "row": index, "severity": "High",
                                "code": "MISSING_CURRENCY",
                                "message": "Financial source row has no currency; excluded from monetary totals."})

    financial = defaultdict(lambda: {"approved_budget": Decimal(0), "actual_cost": Decimal(0),
                                     "open_commitments": Decimal(0), "recognised_revenue": Decimal(0)})
    # Prefer accounting's consolidated project position. Detail collections are
    # fallback inputs only, preventing double counting when both are connected.
    position_rows = data.get("project_positions", [])
    for row in position_rows:
        currency = str(row.get("currency") or "").strip().upper()
        if not currency:
            continue
        bucket = financial[currency]
        bucket["approved_budget"] += _number(row.get("approved_budget"), "approved_budget")
        bucket["actual_cost"] += _number(row.get("actual_cost"), "actual_cost")
        bucket["open_commitments"] += _number(row.get("open_commitments"), "open_commitments")
    if not position_rows:
        for collection, metric in (("cost_actuals", "actual"), ("commitments", "commitment")):
            for row in data.get(collection, []):
                currency = str(row.get("currency") or "").strip().upper()
                if not currency:
                    continue
                if metric == "actual": financial[currency]["actual_cost"] += _number(row.get("amount"), "amount")
                else: financial[currency]["open_commitments"] += _number(row.get("open_amount", row.get("amount")), "commitment amount")
    for row in data.get("recognised_revenue", []):
        currency = str(row.get("currency") or "").strip().upper()
        if not currency:
            continue
        financial[currency]["recognised_revenue"] += _number(row.get("amount"), "revenue amount")

    financial_summary = []
    for currency, values in sorted(financial.items()):
        exposure = values["actual_cost"] + values["open_commitments"]
        financial_summary.append({"currency": currency,
            **{key: float(value) for key, value in values.items()},
            "budget_exposure": float(exposure),
            "available_budget": float(values["approved_budget"] - exposure),
            "contribution_after_cost": float(values["recognised_revenue"] - values["actual_cost"])})

    sources = {}
    for name, state in provenance.items():
        sources[name] = {"status": state.get("status", "unknown"),
                         "records": state.get("records", 0),
                         "collections": state.get("collections", []),
                         "read_only": bool(state.get("read_only", True))}
    connected = sum(1 for value in sources.values() if value["status"] == "connected")
    return {
        "company_scope": integration_result.get("company_scope"),
        "project_scope": integration_result.get("project_scope"),
        "financial_by_currency": financial_summary,
        "source_health": {"sources": sources, "connected_count": connected,
                          "source_count": len(sources),
                          "qualification": "Adapter connection status only; reconciliation and freshness require deployment controls."},
        "data_quality": {"issue_count": len(quality),
                         "high_count": sum(1 for item in quality if item["severity"] == "High"),
                         "issues": quality[:500], "truncated": len(quality) > 500},
        "record_counts": counts,
        "metadata": {"read_only": True, "currency_policy": "No implicit FX conversion.",
                     "source_of_truth": "authoritative Velora upstream applications",
                     "actuals_must_be_posted_and_reconciled_by_source_adapter": True},
    }
