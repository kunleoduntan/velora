"""Preview Entry: the accounting entries a document makes (or will make), in one clean table.

* A submitted document shows the entries that were really posted, read from the ledger (nothing is recomputed, so what you see is what the books hold).
* A draft invoice or return shows the entries it will post, built by the same posting adapter that posts it on submit, and checked for balance.
* Other drafts say plainly that their entries are created on submit, rather than showing a guess.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from velora import db, get_doc, throw
from velora.db.tables import get_table

PREVIEWABLE_DRAFTS = {
    "Sales Invoice": ("velora_erp.finance.invoices", "InvoicePostingAdapter", "Sales"),
    "Purchase Invoice": ("velora_erp.finance.invoices", "InvoicePostingAdapter", "Purchase"),
    "Sales Return": ("velora_erp.finance.returns", "ReturnPostingAdapter", "Sales"),
    "Purchase Return": ("velora_erp.finance.returns", "ReturnPostingAdapter", "Purchase"),
}
ZERO = Decimal("0")


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _account_labels(names: set[str]) -> dict[str, str]:
    if not names:
        return {}
    t = get_table("Account")
    with db.transaction() as c:
        rows = c.execute(select(t.c.name, t.c.account_code, t.c.account_name).where(t.c.name.in_(names))).all()
    return {r[0]: f"{r[1]} · {r[2]}" if r[1] else str(r[2] or r[0]) for r in rows}


def _result(status: str, note: str, rows: list[dict], currency: str, base_currency: str | None, extra: dict | None = None) -> dict:
    labels = _account_labels({r["account"] for r in rows})
    for r in rows:
        r["account_label"] = labels.get(r["account"], r["account"])
    debit = sum((_d(r["debit"]) for r in rows), ZERO); credit = sum((_d(r["credit"]) for r in rows), ZERO)
    base_debit = sum((_d(r.get("base_debit", r["debit"])) for r in rows), ZERO); base_credit = sum((_d(r.get("base_credit", r["credit"])) for r in rows), ZERO)
    out = {"status": status, "note": note, "currency": currency, "base_currency": base_currency or currency, "rows": rows,
           "total_debit": str(debit), "total_credit": str(credit), "total_base_debit": str(base_debit), "total_base_credit": str(base_credit),
           "balanced": debit == credit and base_debit == base_credit}
    out.update(extra or {})
    return out


def _posted(doc) -> dict:
    t = get_table("Account Ledger Record")
    with db.transaction() as c:
        recs = c.execute(select(t).where(t.c.source_doctype == doc.doctype, t.c.source_name == doc.name).order_by(t.c.posting_event, t.c.posting_line)).mappings().all()
    rows = [{"account": r["account"], "debit": str(r["debit"] or 0), "credit": str(r["credit"] or 0), "base_debit": str(r["base_debit"] or 0), "base_credit": str(r["base_credit"] or 0),
             "party": r["party"], "party_type": r["party_type"], "cost_centre": r["cost_centre"], "description": r["line_description"], "event": r["posting_event"],
             "item": r["item"], "warehouse": r["warehouse"]} for r in recs]
    if not rows:
        return _result("None", "This document has not posted any accounting entries.", [], getattr(doc, "currency", "") or "", None)
    first = recs[0]
    cancelled = int(getattr(doc, "docstatus", 0) or 0) == 2
    note = "Entries posted to the ledger" + (" (the document is cancelled; the reversal is listed with it)." if cancelled else ".")
    return _result("Posted", note, rows, first["currency"], first["base_currency"], {"posting_date": str(first["posting_date"]), "exchange_rate": str(first["exchange_rate"])})


def _draft(doc) -> dict:
    spec = PREVIEWABLE_DRAFTS.get(doc.doctype)
    if not spec:
        return _result("Unavailable", f"A {doc.doctype} creates its accounting entries when it is submitted, so there is nothing to preview yet.", [], getattr(doc, "currency", "") or "", None)
    import importlib
    module, cls, kind = spec
    instruction = getattr(importlib.import_module(module), cls)(kind).build_posting(doc)
    rows = [{"account": l.account, "debit": str(_d(l.debit)), "credit": str(_d(l.credit)), "party": l.party, "party_type": l.party_type, "cost_centre": l.cost_centre,
             "description": l.line_description, "event": instruction.posting_event, "item": l.item, "warehouse": l.warehouse} for l in instruction.lines]
    rate = _d(instruction.exchange_rate) or Decimal("1")
    for r in rows:
        r["base_debit"] = str((_d(r["debit"]) * rate).quantize(Decimal("0.01"))); r["base_credit"] = str((_d(r["credit"]) * rate).quantize(Decimal("0.01")))
    stock_note = ""
    if any(getattr(l, "item_code", None) for l in (doc.lines or [])):
        stock_note = " Cost-of-sales and inventory entries for stock items are added when the document is submitted."
    return _result("Preview", "These entries will post when the document is submitted; nothing has been posted yet." + stock_note, rows, instruction.currency, None,
                   {"posting_date": str(instruction.posting_date), "exchange_rate": str(instruction.exchange_rate)})


def preview_entries(doctype: str, name: str) -> dict:
    doc = get_doc(doctype, name)                       # raises unless the user may read the document
    if int(getattr(doc, "docstatus", 0) or 0) in (1, 2):
        return _posted(doc)
    return _draft(doc)
