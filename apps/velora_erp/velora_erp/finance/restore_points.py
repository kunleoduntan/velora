"""Restore points: put back what a document changed on OTHER records when it is cancelled.

Some documents do more than post to the ledger. A depreciation run changes the asset's accumulated depreciation, a loan
repayment changes the loan's outstanding balance, a payroll run changes the slips, inputs and loan schedule. Working those
numbers backwards by formula is error-prone, so the framework does what ERPNext's `on_cancel` does in spirit but exactly:

* just before the document is submitted, a copy of the records it is going to change is saved (Posting Restore Point);
* when it is cancelled, those records are put back to the saved values (rows the document added are removed, rows it removed
  are put back);
* a cancel is refused, with a message naming the later document, when something else has changed the same records since
  (for assets: a later event in the Fixed Asset History Log). Cancel the later document first (or use Cancel All).

Each family registers a `scope(doc)` that returns the selectors (doctype, column, values) of the records involved.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, insert, select, update

from velora import db, get_doc, new_doc, throw
from velora.db.tables import get_table

_SKIP = {"name", "creation", "owner"}


def _list(*names):
    return sorted({n for n in names if n})


def _asset_selectors(assets):
    return [("Fixed Asset", "name", assets), ("Fixed Asset Component", "parent", assets), ("Fixed Asset Book Balance", "asset", assets)]


def _assets_of(doc):
    found = [getattr(doc, "asset", None), getattr(doc, "right_of_use_asset", None)]
    for table in ("lines", "items"):
        found += [getattr(l, "asset", None) for l in (getattr(doc, table, None) or [])]
    lease = getattr(doc, "lease", None)
    if lease and db.exists("Fixed Asset Lease", lease):
        found.append(get_doc("Fixed Asset Lease", lease, ignore_permissions=True).right_of_use_asset)
    return _list(*found)


def _asset_scope(doc):
    return _asset_selectors(_assets_of(doc))


def _lease_scope(doc):
    return _asset_selectors(_assets_of(doc)) + [("Fixed Asset Lease", "name", [doc.lease]), ("Fixed Asset Lease Payment", "parent", [doc.lease])]


def _cgu_scope(doc):
    return _asset_selectors(_assets_of(doc)) + [("Fixed Asset CGU", "name", [doc.cgu]), ("Fixed Asset CGU Other Asset", "parent", [doc.cgu])]


def _names(rows, key):
    out = []
    for r in rows or []:
        v = r.get(key) if isinstance(r, dict) else getattr(r, key, None)
        if v:
            out.append(v)
    return out


def _payroll_run_scope(doc):
    loans, advances, inputs, reviews = [], [], [], []
    for line in doc.employees or []:
        loans += _names(line.loan_recovery_allocations, "employee_loan")
        advances += _names(line.advance_recovery_allocations, "employee_advance")
        inputs += list(line.payroll_input_refs or [])
        reviews += [t.get("credit_review_reference") for t in _tax_rows(line) if t.get("credit_review_reference")]
    loans, advances, inputs, reviews = _list(*loans), _list(*advances), _list(*inputs), _list(*reviews)
    return [("Employee Loan", "name", loans), ("Employee Loan Schedule Line", "parent", loans), ("Employee Advance", "name", advances),
            ("Payroll Input", "name", inputs), ("Tax Refund Credit Review", "name", reviews)]


def _tax_rows(line):
    from velora_erp.finance.payroll_documents import _as_rows
    return _as_rows(getattr(line, "tax_computation", None))


def _loan_repayment_scope(doc):
    return [("Employee Loan", "name", [doc.employee_loan]), ("Employee Loan Schedule Line", "parent", [doc.employee_loan])]


def _advance_settlement_scope(doc):
    return [("Employee Advance", "name", [doc.employee_advance])]


def _payroll_payment_scope(doc):
    return [("Salary Slip", "name", _list(*_names(doc.lines, "salary_slip")))]


def _year_end_scope(doc):
    from velora_erp.finance.year_end_documents import _periods
    periods = _periods(doc.financial_year)
    return [("Financial Year", "name", [doc.financial_year]), ("Financial Period", "name", [periods[-1]["name"]] if periods else [])]


SCOPES: dict = {
    "Year End Close": _year_end_scope,
    "Financial Period Close": lambda doc: [("Financial Period", "name", [doc.financial_period])],
    "Deferred Tax Posting Inbox": lambda doc: [("Deferred Tax Assessment", "name", [doc.source_assessment])],
    "Payroll Run": _payroll_run_scope,
    "Employee Loan Repayment": _loan_repayment_scope,
    "Employee Advance Settlement": _advance_settlement_scope,
    "Payroll Payment": _payroll_payment_scope,
    "Fixed Asset Depreciation Run": _asset_scope,
    "Fixed Asset Revaluation": _asset_scope,
    "Fixed Asset Impairment": _asset_scope,
    "Fixed Asset Disposal": _asset_scope,
    "Fixed Asset Transfer": _asset_scope,
    "Fixed Asset Component Adjustment": _asset_scope,
    "Fixed Asset CGU Impairment": _cgu_scope,
    "Fixed Asset CGU Impairment Reversal": _cgu_scope,
    "Fixed Asset Lease Modification": _lease_scope,
    "Fixed Asset Lease Termination": _lease_scope,
}


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def _coerce(col, v):
    """JSON gives back strings; put dates, numbers and flags back into the type the column stores."""
    if v is None:
        return None
    try:
        pt = col.type.python_type
    except NotImplementedError:
        return v
    if pt is datetime and isinstance(v, str):
        return datetime.fromisoformat(v)
    if pt is date and isinstance(v, str):
        return date.fromisoformat(v[:10])
    if pt is Decimal and not isinstance(v, Decimal):
        return Decimal(str(v))
    return v


def _rows(conn, doctype, column, values):
    if not values:
        return []
    t = get_table(doctype)
    return [dict(r) for r in conn.execute(select(t).where(t.c[column].in_(values))).mappings()]


def capture(doc, method=None):
    """`before_submit` for every document: keep a copy of what the document is about to change."""
    scope = SCOPES.get(doc.doctype)
    if scope is None:
        return
    selectors = [(d, c, list(v)) for d, c, v in scope(doc)]
    with db.transaction() as conn:
        rows = {d: [] for d, _, _ in selectors}
        for d, c, v in selectors:
            rows[d] += [{k: _plain(x) for k, x in r.items()} for r in _rows(conn, d, c, v)]
    point = new_doc("Posting Restore Point", source_doctype=doc.doctype, source_name=doc.name,
                    snapshot={"selectors": selectors, "rows": rows})
    point.flags.trusted_source = True
    point.insert(ignore_permissions=True)


_VOLATILE = {"modified", "modified_by"}


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except Exception:
        return str(_plain(a)) == str(_plain(b))


def capture_after(doc, method=None):
    """`on_submit` for every document: remember what the document changed, so a cancel can tell if anything else has touched it since."""
    if doc.doctype not in SCOPES:
        return
    t = get_table("Posting Restore Point")
    point = _point(doc)
    if point is None:
        return
    snap = point["snapshot"] if isinstance(point["snapshot"], dict) else json.loads(point["snapshot"])
    after = {}
    with db.transaction() as conn:
        for doctype, column, values in snap["selectors"]:
            before = {r["name"]: r for r in snap["rows"].get(doctype, [])}
            for r in _rows(conn, doctype, column, values):
                old = before.get(r["name"])
                if old is None:
                    continue
                changed = {k: _plain(v) for k, v in r.items() if k not in _VOLATILE and k not in _SKIP and not _same(old.get(k), v)}
                if changed:
                    after.setdefault(doctype, {})[r["name"]] = changed
        snap["after"] = after
        conn.execute(update(t).where(t.c.name == point["name"]).values(snapshot=snap))


def _assert_untouched(doc, snap):
    """Every value this document set must still be there; if not, a later document has used the record."""
    with db.transaction() as conn:
        for doctype, column, values in snap["selectors"]:
            current = {r["name"]: r for r in _rows(conn, doctype, column, values)}
            for name, cols in (snap.get("after") or {}).get(doctype, {}).items():
                row = current.get(name)
                if row is None:
                    continue
                moved = [c for c, v in cols.items() if not _same(row.get(c), v)]
                if moved:
                    throw(f"{doc.doctype} {doc.name} cannot be cancelled: {doctype} {name} has been changed since ({', '.join(moved[:3])}) "
                          "by a later document. Cancel the later documents first (or use Cancel All).")


def _point(doc):
    t = get_table("Posting Restore Point")
    with db.transaction() as conn:
        r = conn.execute(select(t).where(t.c.source_doctype == doc.doctype, t.c.source_name == doc.name)).mappings().first()
    return dict(r) if r else None


def _assert_latest(doc, point, assets):
    """Nothing else may have touched these assets since this document was submitted."""
    if not assets:
        return
    h = get_table("Fixed Asset History Log")
    with db.transaction() as conn:
        later = conn.execute(select(h.c.asset, h.c.source_doctype, h.c.source_name, h.c.event_type).where(
            h.c.asset.in_(assets), h.c.creation > point["creation"], h.c.source_name != doc.name)).all()
    if later:
        names = sorted({f"{r[1]} {r[2]}" for r in later if r[2]})[:5]
        throw(f"{doc.doctype} {doc.name} cannot be cancelled: {later[0][0]} has had later activity ({', '.join(names)}). "
              "Cancel those first (or use Cancel All).")


def restore(doc, report) -> None:
    """`on_cancel` side: put the saved records back."""
    scope = SCOPES.get(doc.doctype)
    if scope is None:
        return
    point = _point(doc)
    if point is None:
        throw(f"{doc.doctype} {doc.name} was submitted before cancelling was supported and has no saved copy of the records it changed, "
              "so it cannot be cancelled safely. Post a correcting document instead, or ask your administrator to run the restore-point backfill.")
    snap = point["snapshot"] if isinstance(point["snapshot"], dict) else json.loads(point["snapshot"])
    _assert_latest(doc, point, _assets_of(doc))
    _assert_untouched(doc, snap)
    changed = 0
    with db.transaction() as conn:
        for doctype, column, values in snap["selectors"]:
            t = get_table(doctype)
            saved = {r["name"]: r for r in snap["rows"].get(doctype, [])}
            now = {r["name"]: r for r in _rows(conn, doctype, column, values)}
            for name in now:
                if name not in saved:
                    conn.execute(delete(t).where(t.c.name == name)); changed += 1
            for name, row in saved.items():
                data = {k: _coerce(t.c[k], v) for k, v in row.items() if k in t.c and k not in _SKIP}
                if name in now:
                    conn.execute(update(t).where(t.c.name == name).values(**data)); changed += 1
                else:
                    conn.execute(insert(t).values(name=name, **{k: _coerce(t.c[k], v) for k, v in row.items() if k in t.c and k != "name"})); changed += 1
        conn.execute(delete(get_table("Posting Restore Point")).where(get_table("Posting Restore Point").c.name == point["name"]))
        h = get_table("Fixed Asset History Log")
        conn.execute(delete(h).where(h.c.source_doctype == doc.doctype, h.c.source_name == doc.name))
    report.note(f"{changed} record(s) put back as they were before this document was submitted")
