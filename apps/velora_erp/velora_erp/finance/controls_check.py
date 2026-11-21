"""Receivables and payables controls check: find the things an auditor or finance controller would ask about.

Read-only. Nothing is changed or posted; each finding lists the documents so someone can go and look.
Amounts are in each document's own currency unless a check says base currency.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, func

from velora import db, get_list, throw
from velora.db.tables import get_table

ROW_LIMIT = 100
ZERO = Decimal("0")


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def _day(v):
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _finding(code, scope, severity, title, why, rows, amount=None):
    return {"code": code, "scope": scope, "severity": severity, "title": title, "why": why, "count": len(rows),
            "amount": float(amount) if amount is not None else None, "rows": rows[:ROW_LIMIT], "truncated": len(rows) > ROW_LIMIT}


def _invoices(doctype, start, end):
    return get_list(doctype, filters=[["docstatus", "=", 1], ["invoice_date", ">=", start], ["invoice_date", "<=", end]], limit=20000, ignore_permissions=True,
                    fields=["name", "party", "invoice_date", "due_date", "currency", "grand_total", "base_grand_total", "amount_settled", "source_doctype", "source_document", "party_reference"])


def _open(doctype):
    return get_list(doctype, filters=[["docstatus", "=", 1]], limit=50000, ignore_permissions=True,
                    fields=["name", "party", "invoice_date", "due_date", "currency", "grand_total", "base_grand_total", "amount_settled"])


def _duplicates(code, scope, rows, noun):
    by = defaultdict(list)
    for r in rows:
        by[(r["party"], r["currency"], _d(r["grand_total"]))].append(r)
    pairs = []
    for group in by.values():
        group.sort(key=lambda r: _day(r["invoice_date"]))
        for a, b in zip(group, group[1:]):
            if abs((_day(b["invoice_date"]) - _day(a["invoice_date"])).days) <= 1:
                pairs.append({"party": a["party"], "first": a["name"], "second": b["name"], "amount": float(_d(a["grand_total"])), "currency": a["currency"],
                              "dates": f'{a["invoice_date"]} / {b["invoice_date"]}'})
    return _finding(code, scope, "Warning", f"Possible duplicate {noun}", f"Same party, same amount and currency, dated within a day of each other.", pairs,
                    sum((_d(p["amount"]) for p in pairs), ZERO))


def _stale(code, scope, doctype, today, days, noun):
    rows = []
    for r in _open(doctype):
        out = _d(r["grand_total"]) - _d(r["amount_settled"])
        due = _day(r["due_date"] or r["invoice_date"])
        late = (today - due).days
        if out > 0 and late > days:
            rows.append({"document": r["name"], "party": r["party"], "due_date": str(due), "days_overdue": late, "outstanding": float(out), "currency": r["currency"]})
    rows.sort(key=lambda r: -r["days_overdue"])
    return _finding(code, scope, "Warning", f"{noun} overdue by more than {days} days", "Old balances are the ones that become bad debts or forgotten liabilities.", rows,
                    sum((_d(r["outstanding"]) for r in rows), ZERO))


def _credit_limits():
    limits = {c["name"]: _d(c["credit_limit"]) for c in get_list("Customer", fields=["name", "credit_limit"], limit=50000, ignore_permissions=True) if _d(c["credit_limit"]) > 0}
    owed: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in _open("Sales Invoice"):
        gross = _d(r["grand_total"])
        if gross > 0 and r["party"] in limits:
            owed[r["party"]] += _d(r["base_grand_total"]) * (gross - _d(r["amount_settled"])) / gross
    rows = [{"customer": k, "credit_limit": float(limits[k]), "outstanding_base": float(v.quantize(Decimal("0.01"))), "over_by": float((v - limits[k]).quantize(Decimal("0.01")))}
            for k, v in owed.items() if v > limits[k]]
    return _finding("AR-CREDIT", "Receivables", "Warning", "Customers over their credit limit", "Open invoices in base currency exceed the limit set on the customer.", rows,
                    sum((_d(r["over_by"]) for r in rows), ZERO))


def _bill_vs_order(rows):
    out = []
    for r in rows:
        if r.get("source_doctype") == "Purchase Order" and r.get("source_document"):
            po = get_list("Purchase Order", filters=[["name", "=", r["source_document"]]], fields=["grand_total", "currency"], limit=1, ignore_permissions=True)
            if po and po[0]["currency"] == r["currency"] and _d(r["grand_total"]) > _d(po[0]["grand_total"]):
                out.append({"bill": r["name"], "party": r["party"], "order": r["source_document"], "bill_total": float(_d(r["grand_total"])),
                            "order_total": float(_d(po[0]["grand_total"])), "over_by": float(_d(r["grand_total"]) - _d(po[0]["grand_total"])), "currency": r["currency"]})
    return _finding("AP-OVER-PO", "Payables", "Warning", "Bills larger than their purchase order", "The supplier billed more than was ordered.", out, sum((_d(r["over_by"]) for r in out), ZERO))


def _bills_without_order(rows):
    out = [{"bill": r["name"], "party": r["party"], "date": str(r["invoice_date"]), "amount": float(_d(r["grand_total"])), "currency": r["currency"]}
           for r in rows if r.get("source_doctype") != "Purchase Order" or not r.get("source_document")]
    return _finding("AP-NO-PO", "Payables", "Info", "Bills with no purchase order", "Not always wrong (rent, utilities), but each should have an approval trail.", out, sum((_d(r["amount"]) for r in out), ZERO))


def _control_accounts(party_type):
    doctype = "Customer" if party_type == "Customer" else "Supplier"
    return sorted({c["control_account"] for c in get_list(doctype, fields=["control_account"], limit=50000, ignore_permissions=True) if c.get("control_account")})


def _untagged(party_type, start, end):
    """Ledger lines on the control accounts that carry no party, so they can never be matched to an invoice."""
    accounts = _control_accounts(party_type)
    if not accounts:
        return _finding(f"CX-{party_type.upper()}-UNTAGGED", "Control accounts", "Error", f"{party_type} control account postings with no {party_type.lower()}", "", [])
    t = get_table("Account Ledger Record")
    q = (select(t.c.source_doctype, t.c.source_name, t.c.account, t.c.posting_date, t.c.base_debit, t.c.base_credit)
         .where(t.c.account.in_(accounts), t.c.posting_date >= start, t.c.posting_date <= end, (t.c.party.is_(None)) | (t.c.party == ""))
         .order_by(t.c.posting_date.desc()).limit(5000))
    with db.transaction() as conn:
        rows = [dict(r) for r in conn.execute(q).mappings()]
    out = [{"document": f'{r["source_doctype"]} {r["source_name"]}', "account": r["account"], "date": str(r["posting_date"]), "debit": float(_d(r["base_debit"])), "credit": float(_d(r["base_credit"]))} for r in rows]
    net = sum((_d(r["debit"]) - _d(r["credit"]) for r in out), ZERO)
    return _finding(f"CX-{party_type.upper()}-UNTAGGED", "Control accounts", "Error", f"{party_type} control account postings with no {party_type.lower()}",
                    "A posting straight to the control account without a party makes the ledger and the customer/supplier balances disagree.", out, net)


def _control_vs_subledger(party_type, to_date):
    """Control account balance against the sum of the party balances posted to it."""
    accounts = _control_accounts(party_type)
    t = get_table("Account Ledger Record")
    rows = []
    for account in accounts:
        with db.transaction() as conn:
            gl = _d(conn.execute(select(func.coalesce(func.sum(t.c.base_debit), 0) - func.coalesce(func.sum(t.c.base_credit), 0)).where(t.c.account == account, t.c.posting_date <= to_date)).scalar())
            sub = _d(conn.execute(select(func.coalesce(func.sum(t.c.base_debit), 0) - func.coalesce(func.sum(t.c.base_credit), 0))
                                  .where(t.c.account == account, t.c.posting_date <= to_date, t.c.party_type == party_type, t.c.party.isnot(None), t.c.party != "")).scalar())
        if gl != sub:
            rows.append({"account": account, "ledger_balance": float(gl), "party_balances": float(sub), "difference": float(gl - sub)})
    return _finding(f"CX-{party_type.upper()}-TIEOUT", "Control accounts", "Error", f"{party_type} control account does not agree to party balances", "The control account balance should equal the sum of the individual party balances.",
                    rows, sum((_d(r["difference"]) for r in rows), ZERO))


def run_checks(from_date, to_date, *, scope="Both", stale_days=90, today=None) -> dict:
    if scope not in ("Both", "Receivables", "Payables"):
        throw("Scope must be Both, Receivables or Payables.")
    start, end = _day(from_date), _day(to_date)
    if start > end:
        throw("From date cannot be after To date.")
    stale_days = max(int(stale_days), 1)
    today = today or date.today()
    findings = []
    if scope in ("Both", "Receivables"):
        findings += [_duplicates("AR-DUP", "Receivables", _invoices("Sales Invoice", start, end), "sales invoices"),
                     _stale("AR-STALE", "Receivables", "Sales Invoice", today, stale_days, "Customer balances"), _credit_limits()]
    if scope in ("Both", "Payables"):
        bills = _invoices("Purchase Invoice", start, end)
        findings += [_duplicates("AP-DUP", "Payables", bills, "supplier bills"), _bill_vs_order(bills), _bills_without_order(bills),
                     _stale("AP-STALE", "Payables", "Purchase Invoice", today, stale_days, "Supplier balances")]
    if scope in ("Both", "Receivables"):
        findings += [_untagged("Customer", start, end), _control_vs_subledger("Customer", end)]
    if scope in ("Both", "Payables"):
        findings += [_untagged("Supplier", start, end), _control_vs_subledger("Supplier", end)]
    return {"from_date": str(start), "to_date": str(end), "scope": scope, "stale_days": stale_days, "findings": findings,
            "summary": {"checks": len(findings), "with_findings": sum(1 for f in findings if f["count"]), "errors": sum(1 for f in findings if f["count"] and f["severity"] == "Error"),
                        "warnings": sum(1 for f in findings if f["count"] and f["severity"] == "Warning")}}
