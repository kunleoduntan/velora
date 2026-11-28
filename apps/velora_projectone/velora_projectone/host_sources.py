"""Read-only source adapters: project figures taken from the ERP ledger and employee master the signed-in user may read."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from velora import get_list, registry

from .projectone.integrations.source_readers import ReadQuery

LEDGER_FIELDS = ["name", "source_doctype", "source_name", "source_line_reference", "posting_event", "posting_date", "project",
                 "base_currency", "base_debit", "base_credit", "account_name_snapshot", "root_type_snapshot", "entry_key"]


def _ledger(root_type: str, query: ReadQuery):
    filters = [["root_type_snapshot", "=", root_type], ["project", "is", "set"]]
    if query.project_id:
        filters = [["root_type_snapshot", "=", root_type], ["project", "=", query.project_id]]
    if query.modified_since:
        filters.append(["modified", ">", query.modified_since])
    return get_list("Account Ledger Record", filters=filters, fields=LEDGER_FIELDS, order_by="posting_date desc", limit=query.limit)


def _amount(row, side_first: str, side_second: str) -> float:
    return float(Decimal(str(row.get(side_first) or 0)) - Decimal(str(row.get(side_second) or 0)))


class AccountingSource:
    source_name = "accounting"

    def read(self, query: ReadQuery):
        if query.collection == "cost_actuals":
            return [{"name": r["name"], "project_id": r["project"], "source_doctype": r["source_doctype"], "source_name": r["source_name"],
                     "source_line": r["source_line_reference"] or r["entry_key"], "posting_reference": r["name"],
                     "posting_date": str(r["posting_date"]), "currency": r["base_currency"],
                     "cost_category": r["account_name_snapshot"], "amount": _amount(r, "base_debit", "base_credit"),
                     "source_status": "Posted"} for r in _ledger("Expense", query)]
        if query.collection == "recognised_revenue":
            return [{"name": r["name"], "project_id": r["project"], "source_doctype": r["source_doctype"], "source_name": r["source_name"],
                     "source_line": r["source_line_reference"] or r["entry_key"], "posting_reference": r["name"],
                     "posting_date": str(r["posting_date"]), "currency": r["base_currency"],
                     "amount": _amount(r, "base_credit", "base_debit"), "source_status": "Posted"}
                    for r in _ledger("Income", query)]
        if query.collection == "project_positions":
            totals = defaultdict(lambda: {"actual_cost": 0.0, "recognised_revenue": 0.0, "open_commitments": 0.0, "currency": None})
            for r in _ledger("Expense", query):
                t = totals[r["project"]]; t["actual_cost"] += _amount(r, "base_debit", "base_credit"); t["currency"] = r["base_currency"]
            for r in _ledger("Income", query):
                t = totals[r["project"]]; t["recognised_revenue"] += _amount(r, "base_credit", "base_debit"); t["currency"] = r["base_currency"]
            orders = ProcurementSource().read(ReadQuery("site", "commitments", project_id=query.project_id, limit=query.limit)) if registry.exists("Purchase Order") else []
            for c in orders:
                t = totals[c["project_id"]]
                if t["currency"] in (None, c["currency"]):
                    t["currency"] = c["currency"]; t["open_commitments"] = t.get("open_commitments", 0.0) + c["open_amount"]
            budgets = {r["name"]: r["approved_budget"] for r in get_list(
                "Project", filters=[["name", "in", list(totals)]], fields=["name", "approved_budget"], limit=len(totals) or 1)} if totals else {}
            return [{"name": p, "project_id": p, "approved_budget": float(budgets.get(p) or 0), **t} for p, t in totals.items()]
        return []


def _base_currency() -> str:
    from velora_erp.finance.source_documents import finance_settings
    return str(finance_settings().get("base_currency") or "")


def _by_project(doctype: str, fields: list[str], query: ReadQuery, extra=None):
    flt = [["project", "=", query.project_id]] if query.project_id else [["project", "is", "set"]]
    flt += [["docstatus", "=", 1]] if extra == "submitted" else []
    if query.modified_since:
        flt.append(["modified", ">", query.modified_since])
    return get_list(doctype, filters=flt, fields=["name", "project", *fields], limit=query.limit)


def _pct(value) -> float:
    return min(max(float(value or 0), 0.0), 100.0) / 100.0


class ProcurementSource:
    """Purchase Orders that name a project: what has been ordered and not yet billed."""
    source_name = "procurement"

    def read(self, query: ReadQuery):
        if query.collection not in ("commitments", "purchase_orders"):
            return []
        rows = _by_project("Purchase Order", ["currency", "grand_total", "per_billed", "supplier_name", "document_date", "document_status"], query, "submitted")
        return [{"name": r["name"], "project_id": r["project"], "source_doctype": "Purchase Order", "source_name": r["name"], "supplier": r["supplier_name"],
                 "currency": r["currency"], "amount": float(r["grand_total"] or 0),
                 "open_amount": 0.0 if r["document_status"] == "Closed" else float(r["grand_total"] or 0) * (1 - _pct(r["per_billed"])),
                 "document_date": str(r["document_date"] or ""), "source_status": r["document_status"]} for r in rows]


class SalesSource:
    """Sales Orders that name a project: what the customer has agreed to and how much has been billed."""
    source_name = "sales"

    def read(self, query: ReadQuery):
        if query.collection not in ("billing_milestones", "customer_contracts"):
            return []
        rows = _by_project("Sales Order", ["currency", "grand_total", "per_billed", "customer_name", "document_date", "document_status"], query, "submitted")
        return [{"name": r["name"], "project_id": r["project"], "source_doctype": "Sales Order", "source_name": r["name"], "customer": r["customer_name"],
                 "currency": r["currency"], "amount": float(r["grand_total"] or 0), "billed_amount": float(r["grand_total"] or 0) * _pct(r["per_billed"]),
                 "document_date": str(r["document_date"] or ""), "source_status": r["document_status"]} for r in rows]


class InventorySource:
    """Approved stock issues that name a project, valued in the company's base currency."""
    source_name = "inventory"

    def read(self, query: ReadQuery):
        if query.collection not in ("material_usage", "stock_commitments"):
            return []
        rows = _by_project("Stock Entry", ["stock_entry_type", "total_value", "posting_date", "entry_status"], query, "submitted")
        base = _base_currency()
        return [{"name": r["name"], "project_id": r["project"], "source_doctype": "Stock Entry", "source_name": r["name"], "currency": base,
                 "amount": float(r["total_value"] or 0), "posting_date": str(r["posting_date"] or ""), "source_status": r["entry_status"]}
                for r in rows if r["stock_entry_type"] == "Material Issue"]


class FixedAssetSource:
    """Fixed assets assigned to a project, with their cost and book value in the base currency."""
    source_name = "fixed_assets"

    def read(self, query: ReadQuery):
        if query.collection not in ("asset_allocations", "depreciation_readings"):
            return []
        rows = _by_project("Fixed Asset", ["asset_name", "acquisition_cost", "accumulated_depreciation", "carrying_amount", "status"], query)
        base = _base_currency()
        return [{"name": r["name"], "project_id": r["project"], "source_doctype": "Fixed Asset", "source_name": r["name"], "asset_name": r["asset_name"],
                 "currency": base, "amount": float(r["acquisition_cost"] or 0), "accumulated_depreciation": float(r["accumulated_depreciation"] or 0),
                 "carrying_amount": float(r["carrying_amount"] or 0), "source_status": r["status"]} for r in rows]


class HrmsSource:
    """People side of the project plan: who is allocated to which project, from ProjectOne's own approved allocations."""
    source_name = "hrms"

    def read(self, query: ReadQuery):
        if query.collection != "allocations":
            return []
        filters = [["project", "=", query.project_id]] if query.project_id else []
        rows = get_list("Project Resource Allocation", filters=filters, limit=query.limit,
                        fields=["name", "project", "resource", "role", "start_date", "end_date",
                                "allocation_percent", "planned_hours", "status"])
        return [{**r, "project_id": r["project"], "start_date": str(r["start_date"] or ""),
                 "end_date": str(r["end_date"] or "")} for r in rows]
