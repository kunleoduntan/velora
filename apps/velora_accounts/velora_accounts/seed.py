"""A ready-to-use chart of accounts, so a new company can post on day one."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from velora import db, get_list, new_doc
from velora.db.tables import get_table


# (name, parent, root_type, account_type, is_group)
CHART = [
    ("Assets", None, "Asset", "", 1), ("Current Assets", "Assets", None, "", 1),
    ("Cash in Hand", "Current Assets", None, "Cash", 0), ("Main Bank Account", "Current Assets", None, "Bank", 0),
    ("Trade Receivables", "Current Assets", None, "Receivable", 0), ("WHT Receivable", "Current Assets", None, "Tax", 0),
    ("VAT Input", "Current Assets", None, "Tax", 0), ("Prepayments", "Current Assets", None, "", 0), ("Staff Advances", "Current Assets", None, "", 0),
    ("Non-Current Assets", "Assets", None, "", 1), ("Property, Plant & Equipment", "Non-Current Assets", None, "Fixed Asset", 0),
    ("Accumulated Depreciation", "Non-Current Assets", None, "Accumulated Depreciation", 0),
    ("Liabilities", None, "Liability", "", 1), ("Current Liabilities", "Liabilities", None, "", 1),
    ("Trade Payables", "Current Liabilities", None, "Payable", 0), ("VAT Output", "Current Liabilities", None, "Tax", 0),
    ("WHT Payable", "Current Liabilities", None, "Tax", 0), ("PAYE Payable", "Current Liabilities", None, "Tax", 0),
    ("Pension Payable", "Current Liabilities", None, "", 0), ("Accrued Expenses", "Current Liabilities", None, "", 0), ("Customer Deposits", "Current Liabilities", None, "", 0),
    ("Non-Current Liabilities", "Liabilities", None, "", 1), ("Long-Term Loans", "Non-Current Liabilities", None, "", 0),
    ("Equity", None, "Equity", "", 1), ("Share Capital", "Equity", None, "", 0), ("Retained Earnings", "Equity", None, "Retained Earnings", 0),
    ("Income", None, "Income", "", 1), ("Sales Revenue", "Income", None, "", 0), ("Other Income", "Income", None, "", 0), ("Interest Income", "Income", None, "", 0), ("Discount Received", "Income", None, "", 0),
    ("Expenses", None, "Expense", "", 1), ("Cost of Sales", "Expenses", None, "Cost of Sales", 0), ("Operating Expenses", "Expenses", None, "", 1),
    ("Salaries & Wages", "Operating Expenses", None, "", 0), ("Rent", "Operating Expenses", None, "", 0), ("Utilities", "Operating Expenses", None, "", 0),
    ("Bank Charges", "Operating Expenses", None, "", 0), ("Discount Allowed", "Operating Expenses", None, "", 0), ("Gateway Fees", "Operating Expenses", None, "", 0), ("Depreciation Expense", "Operating Expenses", None, "", 0),
    ("Professional Fees", "Operating Expenses", None, "", 0), ("Office Expenses", "Operating Expenses", None, "", 0), ("Travel & Transport", "Operating Expenses", None, "", 0),
    ("Finance Costs", "Expenses", None, "", 0),
]
DEFAULTS = {"receivable": "Trade Receivables", "payable": "Trade Payables", "wht_payable": "WHT Payable", "wht_receivable": "WHT Receivable",
            "gateway_fees": "Gateway Fees", "prepayments": "Prepayments", "discount_allowed": "Discount Allowed", "discount_received": "Discount Received", "sales_income": "Sales Revenue", "retained_earnings": "Retained Earnings"}


def seed_chart() -> int:
    """Create the starter chart and default accounts. Idempotent: does nothing if the company already has accounts."""
    if get_list("Account", fields=["name"], limit=1):
        return 0
    for name, parent, root, atype, grp in CHART:
        new_doc("Account", account_name=name, parent_account=parent, root_type=root, account_type=atype or None, is_group=grp).insert(ignore_permissions=True)
    from velora.settings import set_setting
    set_setting("accounts.defaults", DEFAULTS)
    ensure_invoicing_setup()
    return len(CHART)


TAX_CODES = [("VAT 7.5% Output", "VAT Output", 7.5, "VAT Output"), ("VAT 0% Output", "VAT Output", 0, "VAT Output"),
             ("VAT 7.5% Input", "VAT Input", 7.5, "VAT Input"), ("VAT 0% Input", "VAT Input", 0, "VAT Input")]


def ensure_invoicing_setup() -> dict:
    """Make sure the accounts, default accounts and tax codes that invoicing needs exist. Only ever ADDS what is missing and never overrides a
    choice you made - so it is safe for new companies (via seed) and for existing ones (via the upgrade patch)."""
    from velora.settings import get_setting, set_setting
    made = {"accounts": [], "defaults": [], "tax_codes": [], "parties": [], "skipped_parties": []}
    have = {a["name"] for a in get_list("Account", fields=["name"], limit=2000)}
    for name, parent, root, atype, grp in CHART:
        if name in ("Discount Allowed", "Discount Received") and name not in have:
            par = parent if parent in have else None
            root_t = root or ("Expense" if name == "Discount Allowed" else "Income")
            new_doc("Account", account_name=name, parent_account=par, root_type=root_t if not par else None, account_type=atype or None, is_group=grp).insert(ignore_permissions=True)
            have.add(name)
            made["accounts"].append(name)
    cur = dict(get_setting("accounts.defaults", {}) or {})
    for kind, acct in DEFAULTS.items():
        if kind not in cur and acct in have:
            cur[kind] = acct
            made["defaults"].append(kind)
    if made["defaults"]:
        set_setting("accounts.defaults", cur)
    existing = {t["name"] for t in get_list("Tax Code", fields=["name"], limit=500)}
    for name, ttype, rate, acct in TAX_CODES:
        if name not in existing and acct in have:
            new_doc("Tax Code", tax_name=name, tax_type=ttype, rate=rate, account=acct).insert(ignore_permissions=True)
            made["tax_codes"].append(name)
    # Customers/suppliers that already have postings (typed as free text before the master existed) get a master record, so that strict party
    # checking never locks anyone out of an existing customer after an upgrade.
    g = get_table("GL Entry")
    with db.transaction() as conn:
        used = conn.execute(select(g.c.party_type, g.c.party).where(g.c.party.is_not(None)).distinct()).all()
    for ptype, party in used:
        if ptype not in ("Customer", "Supplier"):
            continue
        if not party.strip() or party != party.strip():
            made["skipped_parties"].append(party)                      # padded/blank names cannot be created as-is: fix them by hand
        elif not get_list(ptype, filters=[["name", "=", party]], fields=["name"], limit=1):
            new_doc(ptype, **{f"{ptype.lower()}_name": party}).insert(ignore_permissions=True)
            made["parties"].append(f"{ptype}: {party}")
    return made


def ensure_fiscal_year(year: int | None = None) -> str:
    year = year or date.today().year
    name = f"FY{year}"
    if not get_list("Fiscal Year", filters=[["name", "=", name]], fields=["name"], limit=1):
        new_doc("Fiscal Year", year_name=name, start_date=date(year, 1, 1), end_date=date(year, 12, 31)).insert(ignore_permissions=True)
    return name


def after_install():
    seed_chart()
    ensure_fiscal_year()
