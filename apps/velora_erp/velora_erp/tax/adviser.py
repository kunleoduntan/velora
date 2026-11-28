"""The tax consultant: deterministic health checks and the figures behind the Tax Hub.

Everything here reads the books and the tax configuration and says what a careful tax adviser would say: what is missing, what
is late, what looks wrong. It never posts or changes anything. Free-form questions go to the AI advisor registered in hooks.py
(`veloraerp.tax.advisor`), which is told to explain and not to invent figures.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from velora import db, get_list
from velora.db.tables import get_table
from velora_erp.tax import deadlines
from velora_erp.tax.service import _d, ledger_rows, load_rules, settings

ZERO = Decimal("0")
# Expense names that usually need a decision on tax deductibility. A prompt to review, never a conclusion.
WATCH = ("fine", "penalt", "donation", "entertain", "depreciation", "amortis", "amortiz", "provision", "bad debt", "impairment", "gift", "personal", "interest on tax", "political")


def _f(severity, area, title, detail, route=None):
    return {"severity": severity, "area": area, "title": title, "detail": detail, "route": route}


def findings(today: date | None = None) -> list[dict]:
    today = today or date.today()
    out: list[dict] = []
    rules = load_rules(None)
    types = {r.tax_type for r in rules}
    for t, why in (("VAT", "invoices cannot be taxed from an approved rate"), ("WHT", "withholding tax cannot be calculated or reported"), ("Income Tax", "company income tax cannot be computed")):
        if t not in types:
            out.append(_f("warning", "Setup", f"No approved {t} rule", f"Without one, {why}. Enter the statutory rate as a Tax Rule and approve it.", "Tax Rule"))
    for r in get_list("Tax Rule", filters=[["docstatus", "=", 1], ["approval_status", "=", "Approved"], ["tax_account", "is", "not set"]], fields=["rule_code", "tax_type"], limit=100, ignore_permissions=True):
        if r["tax_type"] in ("VAT", "WHT", "Levy"):
            out.append(_f("warning", "Setup", f"Rule {r['rule_code']} has no tax account", "Invoices and tax journals need the account the tax is posted to.", "Tax Rule"))
    if not settings().get("default_jurisdiction"):
        out.append(_f("info", "Setup", "No default jurisdiction", "Set one in Tax Settings so new tax documents are pre-filled.", "Tax Settings"))
    # obligations
    window = int(settings().get("filing_reminder_days") or 7)
    for o in get_list("Tax Obligation", filters=[["status", "in", ["Open", "In Preparation", "Under Review", "Rejected"]]], fields=["name", "tax_type", "jurisdiction", "due_date", "period_start", "period_end"], limit=500, ignore_permissions=True):
        due = o["due_date"] if isinstance(o["due_date"], date) else date.fromisoformat(str(o["due_date"])[:10])
        if due < today:
            ex = deadlines.exposure({**o, "jurisdiction": o.get("jurisdiction"), "period_start": o["period_start"]}, today)
            money = f" Estimated exposure from the rates in Tax Settings: tax {ex['tax']:,.2f}, penalty {ex['penalty']:,.2f}, interest {ex['interest']:,.2f}." if (ex["penalty"] or ex["interest"]) else " Late filing and payment attract penalties and interest; set the rates in Tax Settings to see an estimate."
            out.append(_f("critical", "Compliance", f"{o['tax_type']} return overdue", f"The {o['tax_type']} obligation for the period ending {o['period_end']} was due {due} ({(today - due).days} days ago).{money}", "Tax Obligation"))
        elif due <= today + timedelta(days=window):
            out.append(_f("warning", "Compliance", f"{o['tax_type']} return due {due}", "Prepare, review and file before the due date.", "Tax Obligation"))
    # tax codes with no rule
    start = date(today.year, 1, 1)
    codes = {r.code for r in rules}
    unknown = sorted({(r["tax_code"] or "").upper() for r in ledger_rows(start, today)} - codes - {""})
    if unknown:
        out.append(_f("critical", "Ledger", "Tax posted under codes with no approved rule", "These codes are in the ledger this year but in no return: " + ", ".join(unknown) + ".", "Tax Rule"))
    # WHT
    h, l = get_table("Tax Journal"), get_table("Tax Journal Line")
    with db.transaction() as c:
        missing = c.execute(select(func.count()).select_from(l.join(h, l.c.parent == h.c.name)).where(h.c.docstatus == 1, l.c.party_type.in_(["Customer", "Income received"]), (l.c.certificate_number.is_(None)) | (l.c.certificate_number == ""))).scalar()
        drafts = {t: c.execute(select(func.count()).select_from(get_table(t)).where(get_table(t).c.docstatus == 0)).scalar() for t in ("Tax Journal", "Income Tax Computation", "Tax Return", "Tax Rule")}
    if missing:
        out.append(_f("warning", "WHT", f"{missing} customer withholding tax row(s) without a certificate", "A credit is only safe to claim against your tax with the customer's certificate. Obtain and record it.", "WHT Register"))
    wht_codes = {r.code for r in rules if r.tax_type == "WHT"}
    credit = sum((r["tax"] for r in ledger_rows(date(today.year - 5, 1, 1), today) if r["section"] == "Input tax" and r["tax_code"].upper() in wht_codes), ZERO)
    if credit > 0:
        out.append(_f("info", "WHT", f"Withholding tax credits of {credit:,.2f} are not yet used", "Set them against company income tax in the computation (or against the tax return), within the period the law allows.", "Income Tax Computation"))
    pending = {k: v for k, v in drafts.items() if v}
    if pending:
        out.append(_f("info", "Workflow", "Draft tax documents waiting", ", ".join(f"{v} {k}" for k, v in pending.items()) + ".", None))
    # accounts that deserve a tax decision
    a = get_table("Account")
    with db.transaction() as c:
        accounts = c.execute(select(a.c.name, a.c.account_name).where(a.c.root_type == "Expense", a.c.is_group == 0, a.c.disabled == 0, (a.c.tax_treatment.is_(None)) | (a.c.tax_treatment == "Allowable"))).mappings().all()
    watch = [x["account_name"] for x in accounts if any(w in (x["account_name"] or "").lower() for w in WATCH)]
    if watch:
        out.append(_f("warning", "Income tax", f"{len(watch)} expense account(s) treated as fully allowable that usually need a decision", ", ".join(sorted(watch)[:12]) + ". Mark the ones the law does not allow as Not tax allowed on the Account.", "Tax Treatment of Accounts"))
    if "Income Tax" in types:
        end_prev = date(today.year - 1, 12, 31)
        if end_prev < today and not get_list("Income Tax Computation", filters=[["period_end", ">=", end_prev]], fields=["name"], limit=1, ignore_permissions=True):
            out.append(_f("info", "Income tax", "No income tax computation for last year", "Prepare the computation from the ledger so the return and payment can be planned.", "Income Tax Computation"))
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda x: (order[x["severity"]], x["area"]))


def dashboard(today: date | None = None) -> dict:
    today = today or date.today()
    start = date(today.year, 1, 1)
    types = {r.code: r.tax_type for r in load_rules(None)}
    rows = ledger_rows(start, today)
    k = {"vat_output": ZERO, "vat_input": ZERO, "wht_payable": ZERO, "wht_credit": ZERO}
    months: dict = {}
    for r in rows:
        t = types.get((r["tax_code"] or "").upper())
        m = months.setdefault(str(r["date"])[:7], {"month": str(r["date"])[:7], "output": 0.0, "input": 0.0})
        if t == "VAT":
            if r["section"] == "Output tax": k["vat_output"] += r["tax"]; m["output"] += float(r["tax"])
            else: k["vat_input"] += r["tax"]; m["input"] += float(r["tax"])
        elif t == "WHT":
            if r["section"] == "Output tax": k["wht_payable"] += r["tax"]
            else: k["wht_credit"] += r["tax"]
    obligations = get_list("Tax Obligation", filters=[["status", "in", ["Open", "In Preparation", "Under Review", "Rejected"]]], fields=["name", "tax_type", "due_date", "status"], order_by="due_date asc", limit=200, ignore_permissions=True)
    def _d8(v): return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    overdue = [o for o in obligations if _d8(o["due_date"]) < today]
    exposure_total = sum((deadlines.exposure(o, today)["total"] for o in get_list("Tax Obligation", filters=[["status", "in", ["Open", "In Preparation", "Under Review", "Rejected"]], ["due_date", "<", today]], fields=["name", "tax_type", "jurisdiction", "due_date", "period_start", "period_end"], limit=200, ignore_permissions=True)), ZERO)
    f = findings(today)
    return {"as_of": str(today), "year_start": str(start), "vat_output": str(k["vat_output"]), "vat_input": str(k["vat_input"]), "vat_net": str(k["vat_output"] - k["vat_input"]),
            "wht_payable": str(k["wht_payable"]), "wht_credit": str(k["wht_credit"]), "open_obligations": len(obligations), "overdue_obligations": len(overdue), "exposure": str(exposure_total),
            "next_due": ({"name": obligations[0]["name"], "tax_type": obligations[0]["tax_type"], "due_date": str(_d8(obligations[0]["due_date"]))} if obligations else None),
            "findings": {"critical": sum(1 for x in f if x["severity"] == "critical"), "warning": sum(1 for x in f if x["severity"] == "warning"), "info": sum(1 for x in f if x["severity"] == "info")},
            "months": [months[m] for m in sorted(months)]}
