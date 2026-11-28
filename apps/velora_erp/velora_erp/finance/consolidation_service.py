"""Collects each group member's balances through that company's own permissions and hands them to the consolidation engine.

Companies live in separate databases, so nothing here reads across them in one go: for every member the code enters that company as
the signed-in person, with the roles they hold THERE, and reads only what those roles allow. A member the person cannot open is
left out and reported; it is never read on the strength of a role held somewhere else."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from velora import get_doc, get_list, registry
from velora.company import current_company
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import check_permission, get_session

from . import consolidation as engine
from . import reporting_provider as provider
from .multicurrency import base_currency, lookup_rate

CHUNK = 400


def _date(v, label) -> date:
    try:
        return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ValidationError(f"{label} is not a valid date") from None


def _plane():
    info = current_company()
    return getattr(getattr(info, "directory", None), "plane", None)


def accessible_companies() -> list[dict]:
    """Companies the signed-in person may enter (id, name, roles). Without a control plane: just the one company they are in."""
    info, plane = current_company(), _plane()
    session = get_session()
    if plane is None:
        return [{"id": info.id if info else "", "name": info.name if info else "This company", "roles": sorted(session.roles), "current": True}]
    user = plane.identity.get_user(session.user)
    rows = plane.identity.companies_for(user["id"]) if user else []
    return [{"id": r["id"], "name": r["name"], "roles": r["roles"], "current": bool(info and r["id"] == info.id), "status": r.get("status", "active")} for r in rows if r.get("status", "active") == "active" and r["roles"]]


@contextmanager
def _enter(company_id: str):
    """Work inside one member company with the roles this person holds in it (or as they are, when it is the company already open)."""
    info, plane = current_company(), _plane()
    if plane is None or (info and company_id in (info.id, "")):
        yield
        return
    session = get_session()
    user = plane.identity.get_user(session.user)
    mine = next((c for c in (plane.identity.companies_for(user["id"]) if user else []) if c["id"] == company_id), None)
    if not mine or not mine["roles"] or mine.get("status", "active") != "active":
        raise PermissionDenied("You do not have access to this company")
    with plane.company_scope(company_id, session.user, tuple(mine["roles"])):
        yield


def _paged(doctype, fields):
    out, start = [], 0
    while True:
        page = get_list(doctype, fields=fields, limit=1000, offset=start)
        out.extend(page)
        if len(page) < 1000:
            return out
        start += 1000


def _totals(names, start, end, *, balance_at_date):
    out = {}
    for i in range(0, len(names), CHUNK):
        for r in provider.get_account_totals(names[i:i + CHUNK], start, end, balance_at_date=balance_at_date):
            out[r["account"]] = Decimal(str(r["debit"] or 0)) - Decimal(str(r["credit"] or 0))
    return out


def _rates(row, base, presentation, start, end):
    """Closing, average, equity and opening rates to the reporting currency: the ones entered on the group, else this company's own rate table."""
    if base == presentation:
        return {"closing": Decimal(1), "average": Decimal(1), "equity": Decimal(1), "opening": Decimal(1)}, []
    notes = []
    given = {k: Decimal(str(getattr(row, f"{k}_rate", 0) or 0)) for k in ("closing", "average", "equity", "opening")}
    closing = given["closing"] or lookup_rate(base, presentation, end)
    if not closing:
        raise ValidationError(f"No exchange rate from {base} to {presentation} on or before {end}. Add it to that company's Currency Exchange Rate, or type a closing rate on the group.")
    opening = given["opening"] or lookup_rate(base, presentation, start - timedelta(days=1)) or lookup_rate(base, presentation, start)
    average = given["average"] or ((opening + closing) / 2 if opening else closing)
    if not given["average"]: notes.append("Average rate taken as the mean of the opening and closing rates.")
    return {"closing": closing, "average": average, "equity": given["equity"] or closing, "opening": opening or closing}, notes


def collect_member(row, presentation, start, end) -> dict:
    """Balances of one company, read as the signed-in person. Raises when they may not read the books or a rate is missing."""
    provider.check_access()
    base = base_currency()
    rates, notes = _rates(row, base, presentation, start, end)
    accounts = provider.get_accounts()
    labels = {a["name"]: a for a in _paged("Account", ["name", "account_name", "account_code"])}
    bs = [a["name"] for a in accounts if a["root_type"] in ("Asset", "Liability", "Equity")]
    pl = [a["name"] for a in accounts if a["root_type"] in ("Income", "Expense")]
    bs_bal = _totals(bs, date(1900, 1, 1), end, balance_at_date=True)
    pl_bal = _totals(pl, start, end, balance_at_date=False)
    prior = sum(_totals(pl, date(1900, 1, 1), start - timedelta(days=1), balance_at_date=True).values(), Decimal(0)) if pl else Decimal(0)
    rows = []
    for a in accounts:
        bal = (bs_bal if a["root_type"] in ("Asset", "Liability", "Equity") else pl_bal).get(a["name"], Decimal(0))
        if bal:
            meta = labels.get(a["name"], {})
            rows.append({"account": a["name"], "code": a.get("account_number") or meta.get("account_code") or "", "label": meta.get("account_name") or a["name"], "root_type": a["root_type"], "balance": bal})
    return {"currency": base, "rates": rates, "accounts": rows, "prior_pl": prior, "notes": notes}


def run_consolidation(group_name: str, from_date, to_date, *, save: bool = False) -> dict:
    meta = registry.get("Consolidation Group")
    check_permission(meta, "read")
    group = get_doc("Consolidation Group", group_name)
    if group.status == "Inactive": raise ValidationError("This consolidation group is inactive")
    start, end = _date(from_date, "The start date"), _date(to_date, "The end date")
    if start > end: raise ValidationError("The start date must not be after the end date")
    presentation = (group.presentation_currency or "").upper()
    names = {c["id"]: c["name"] for c in accessible_companies()}
    members, problems = [], []
    for row in group.members or []:
        if not row.include: continue
        cid = row.company_id
        try:
            with _enter(cid):
                data = collect_member(row, presentation, start, end)
        except (PermissionDenied, ValidationError) as exc:
            problems.append({"level": "error", "code": "member_unavailable", "company": cid, "message": f"{names.get(cid, cid)} was left out: {exc}"})
            continue
        members.append({"company_id": cid, "name": names.get(cid) or cid, "ownership": Decimal(str(row.ownership_percent or 100)), "method": row.method or "Full", **data})
    maps = [{"company_id": m.company_id, "account": m.account, "group_code": m.group_code, "group_name": m.group_name} for m in group.mappings or []]
    rules = [{"description": r.description, "rule_type": r.rule_type, "company_one": r.company_one, "account_one": r.account_one, "company_two": r.company_two, "account_two": r.account_two,
              "basis": r.basis, "fixed_amount": r.fixed_amount, "enabled": bool(r.enabled)} for r in group.eliminations or []]
    result = engine.consolidate(members, currency=presentation, mappings=maps, rules=rules, tolerance=Decimal(str(group.tolerance if group.tolerance is not None else 1)))
    for m in members:                                                      # carry each company's own notes (rates assumed, etc.)
        for n in m.get("notes", []): result["checks"].append({"level": "info", "code": "rate_note", "company": m["company_id"], "message": f"{m['name']}: {n}"})
    result["checks"] = problems + result["checks"]
    if problems or not members: result["ok"] = False
    if not members: result["checks"].append({"level": "error", "code": "no_members", "company": "", "message": "No company in this group could be read, so there is nothing to consolidate."})
    result.update({"group": group.name, "from_date": start.isoformat(), "to_date": end.isoformat()})
    out = _plain(result)
    if save:
        errors = sum(1 for c in out["checks"] if c["level"] == "error"); warnings = sum(1 for c in out["checks"] if c["level"] == "warning")
        from velora import new_doc
        doc = new_doc("Consolidation Run", group=group.name, from_date=start, to_date=end, presentation_currency=presentation, ok=1 if out["ok"] else 0, error_count=errors, warning_count=warnings,
                      generated_by=get_session().user, generated_on=datetime.now(timezone.utc).replace(tzinfo=None), result=out)
        doc.insert()
        out["saved_as"] = doc.name
    return out


def _plain(v):
    """Decimals to floats (two places) and tuples to lists, so the result can be stored and sent as JSON."""
    if isinstance(v, Decimal): return float(v.quantize(Decimal("0.01")))
    if isinstance(v, dict): return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [_plain(x) for x in v]
    return v


def to_report(result: dict, view: str):
    """The same figures as an exportable report: worksheet, income statement, balance sheet or checks."""
    from velora.reporting.model import Column, ReportBuilder
    cur = result["currency"]
    sub = f"{result['group']} · {result['from_date']} to {result['to_date']}"
    if view == "income":
        rb = ReportBuilder("Consolidated Income Statement", [Column("label", "Line"), Column("amount", "Amount", "Currency")], sub, cur)
        s = result["income_statement"]
        rb.section("Income"); [rb.row({"label": r["label"], "amount": r["amount"]}) for r in s["income"]["rows"]]; rb.subtotal("Total income")
        rb.section("Expenses"); [rb.row({"label": r["label"], "amount": r["amount"]}) for r in s["expense"]["rows"]]; rb.subtotal("Total expenses")
        rb.row({"label": "Profit for the period", "amount": s["profit"]}); rb.row({"label": "Attributable to owners of the group", "amount": s["profit_attributable_to_owners"]}); rb.row({"label": "Attributable to non-controlling interests", "amount": s["non_controlling_profit"]})
        return rb.build()
    if view == "balance":
        rb = ReportBuilder("Consolidated Balance Sheet", [Column("label", "Line"), Column("amount", "Amount", "Currency")], sub, cur)
        b = result["balance_sheet"]
        for title, key in (("Assets", "assets"), ("Liabilities", "liabilities"), ("Equity", "equity")):
            rb.section(title); [rb.row({"label": r["label"], "amount": r["amount"]}) for r in b[key]["rows"]]
            if key == "equity": rb.row({"label": "Profit for the period", "amount": b["current_result"]})
            rb.subtotal(f"Total {title.lower()}")
        rb.row({"label": "of which non-controlling interests", "amount": b["non_controlling_interest"]})
        return rb.build()
    if view == "checks":
        rb = ReportBuilder("Consolidation Checks", [Column("level", "Level"), Column("company", "Company"), Column("message", "What was found")], sub, cur)
        [rb.row({"level": c["level"].title(), "company": c.get("company", ""), "message": c["message"]}) for c in result["checks"]]
        return rb.build()
    cols = [Column("label", "Account")] + [Column(f"m_{i}", m["name"], "Currency") for i, m in enumerate(result["members"])] + [Column("elim", "Eliminations", "Currency"), Column("total", "Consolidated", "Currency")]
    rb = ReportBuilder("Consolidation Worksheet", cols, sub, cur)
    for root in ("Asset", "Liability", "Equity", "Income", "Expense"):
        rows = [l for l in result["lines"] if l["root_type"] == root]
        if not rows: continue
        rb.section(root)
        for l in rows:
            rb.row({"label": f"{l['key']} · {l['label']}" if not l["key"].startswith("~") else l["label"], **{f"m_{i}": l["cells"].get(m["company_id"], 0) for i, m in enumerate(result["members"])}, "elim": l["elimination"], "total": l["total"]})
        rb.subtotal(f"Total {root.lower()}")
    return rb.build()
