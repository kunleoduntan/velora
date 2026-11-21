"""Shared helpers for HR reports: guarded reads, date handling and employee lookup."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from velora import get_list, throw
from velora.meta.registry import registry
from velora.permissions import check_permission

CAP = 5000
HR_ROLES = ["System Manager", "HR Manager", "HR User", "Auditor"]
PAYROLL_ROLES = ["System Manager", "HR Manager", "Payroll Manager", "Finance Manager", "Auditor"]


def as_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def period(filters, *, default_days=365):
    end = as_date(filters.get("to_date")) or date.today()
    start = as_date(filters.get("from_date")) or end - timedelta(days=default_days)
    if start > end:
        throw("From Date cannot be after To Date.")
    return start, end


def read(doctype, fields, filters=None, order_by=None):
    """Permission-checked read capped at CAP rows; refuses silently-truncated results."""
    check_permission(registry.get(doctype), "read")
    # Permissions stay ON: row policies and field-level access of the viewer apply to every report row.
    rows = get_list(doctype, filters=filters or {}, fields=fields, order_by=order_by, limit=CAP + 1)
    if len(rows) > CAP:
        throw(f"More than {CAP:,} {doctype} records matched. Narrow the report filters.")
    return rows


def employees(filters=None, *, include_disabled=False):
    """Employees matching the common Department / Branch / Employee filters, keyed by name."""
    filters = filters or {}
    cond = {}
    for key in ("department", "branch", "designation", "employee_type", "grade"):
        if filters.get(key):
            cond[key] = filters[key]
    if filters.get("employee"):
        cond["name"] = filters["employee"]
    if not include_disabled:
        cond["disabled"] = 0
    rows = read("Employee", ["name", "employee_name", "department", "designation", "branch", "grade", "employee_type",
                             "date_of_joining", "email", "phone", "disabled", "default_cost_centre", "default_business_unit"], cond, "employee_name")
    return {r["name"]: r for r in rows}


def years_between(start, end):
    start, end = as_date(start), as_date(end)
    if not start or not end or end < start:
        return None
    return round((end - start).days / 365.25, 1)


def common_filters(*extra):
    base = [
        {"fieldname": "department", "label": "Department", "fieldtype": "Link", "options": "Department"},
        {"fieldname": "branch", "label": "Branch", "fieldtype": "Link", "options": "Branch"},
        {"fieldname": "employee", "label": "Employee", "fieldtype": "Link", "options": "Employee"},
    ]
    return base + list(extra)


def date_filters():
    return [{"fieldname": "from_date", "label": "From Date", "fieldtype": "Date"},
            {"fieldname": "to_date", "label": "To Date", "fieldtype": "Date"}]
