"""One flat table of every tax line in the ledger, enriched with its rule: the base for the Tax Report Library."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from velora import db
from velora.db.tables import get_table
from velora_erp.tax.service import _d, load_rules

ZERO = Decimal("0")


def as_date(v):
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    return date.fromisoformat(str(v)[:10]) if v not in (None, "") else None


def rule_index():
    """{code: rule} using the rule in force most recently (rules of one code share type and jurisdiction)."""
    out = {}
    for r in load_rules(None):
        cur = out.get(r.code)
        if cur is None or r.effective_from >= cur.effective_from:
            out[r.code] = r
    return out


def facts(start, end) -> list[dict]:
    r, a = get_table("Account Ledger Record"), get_table("Account")
    q = (select(r.c.name, r.c.posting_date, r.c.source_doctype, r.c.source_name, r.c.party_type, r.c.party, r.c.account, r.c.tax_code, r.c.tax_rate, r.c.base_debit, r.c.base_credit,
                r.c.base_taxable_amount, r.c.taxable_amount, r.c.item, r.c.cost_centre, r.c.branch, r.c.business_unit, r.c.tax_jurisdiction, r.c.creation, a.c.account_name, a.c.root_type)
         .join(a, a.c.name == r.c.account).where(r.c.tax_code.is_not(None), r.c.tax_code != "", r.c.posting_date >= start, r.c.posting_date <= end))
    with db.transaction() as c:
        rows = c.execute(q.order_by(r.c.posting_date, r.c.name)).mappings().all()
    rules = rule_index()
    out = []
    for x in rows:
        dr, cr = _d(x["base_debit"]), _d(x["base_credit"])
        if x["root_type"] == "Liability": section, tax = "Output", cr - dr
        elif x["root_type"] == "Asset": section, tax = "Input", dr - cr
        else: continue
        code = (x["tax_code"] or "").strip().upper()
        rule = rules.get(code)
        net = _d(x["base_taxable_amount"] or x["taxable_amount"])
        out.append({"record": x["name"], "date": as_date(x["posting_date"]), "source_doctype": x["source_doctype"] or "", "source_name": x["source_name"] or "", "party_type": x["party_type"] or "",
                    "party": x["party"] or "", "account": x["account"], "account_name": x["account_name"], "section": section, "tax_code": code, "rate": float(_d(x["tax_rate"])),
                    "net": net if tax >= 0 else -net, "tax": tax, "item": x["item"] or "", "cost_centre": x["cost_centre"] or "", "branch": x["branch"] or "", "business_unit": x["business_unit"] or "",
                    "jurisdiction": (rule.jurisdiction if rule else None) or x["tax_jurisdiction"] or "", "tax_type": rule.tax_type if rule else "(no rule)", "category": (rule.category if rule else "") or "",
                    "inclusive": bool(rule.inclusive) if rule else False, "recoverable_pct": float(rule.recoverability_percent) if rule else 100.0, "created": as_date(x["creation"])})
    return out
