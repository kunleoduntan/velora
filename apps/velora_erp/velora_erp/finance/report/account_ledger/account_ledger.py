from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from velora import db, throw
from velora.db.tables import get_table
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.finance.reporting_utils import financial_year_start

MAX_ROWS = 5000


def execute(filters):
    check_access()
    account = filters.get("account") or None
    account_from = filters.get("account_from") or None
    account_to = filters.get("account_to") or None
    party = (filters.get("party") or "").strip() or None
    party_type = filters.get("party_type") or None
    if not account and not party and not account_from and not account_to:
        throw("Select an Account, an Account From/To range, or enter a Party to run the Account Ledger.")
    end = filters.get("to_date") or date.today()
    start = filters.get("from_date") or financial_year_start(end)
    if start > end:
        throw("From Date cannot be after To Date.")
    ledger = get_table("Account Ledger Record")
    accounts = get_table("Account")
    settings = get_table("Finance Settings")
    bounds = [x for x in (account_from, account_to) if x]
    account_codes = {}
    if bounds:
        with db.transaction() as conn:
            account_codes = {r["name"]: r["account_code"] for r in conn.execute(
                select(accounts.c.name, accounts.c.account_code).where(accounts.c.name.in_(bounds))).mappings()}
        if any(x not in account_codes for x in bounds):
            throw("Select valid Account From and Account To records.")
        if account_from and account_to and str(account_codes[account_from]) > str(account_codes[account_to]):
            throw("Account From cannot be after Account To by account code.")
    conditions = []
    if account:
        conditions.append(ledger.c.account == account)
    if account_from:
        conditions.append(accounts.c.account_code >= account_codes[account_from])
    if account_to:
        conditions.append(accounts.c.account_code <= account_codes[account_to])
    if party:
        conditions.append(ledger.c.party == party)
    if party_type:
        conditions.append(ledger.c.party_type == party_type)
    if filters.get("cost_centre"):
        conditions.append(ledger.c.cost_centre == filters["cost_centre"])
    with db.transaction() as conn:
        opening_query = select(
            ledger.c.account,
            func.coalesce(func.sum(ledger.c.base_debit), 0).label("debit"),
            func.coalesce(func.sum(ledger.c.base_credit), 0).label("credit"),
        ).select_from(ledger.join(accounts, ledger.c.account == accounts.c.name))\
         .where(*conditions, ledger.c.posting_date < start).group_by(ledger.c.account)
        opening_rows = [dict(r) for r in conn.execute(opening_query).mappings().all()]
        rows = conn.execute(
            select(ledger, accounts.c.account_code, accounts.c.account_name)
            .select_from(ledger.join(accounts, ledger.c.account == accounts.c.name))
            .where(*conditions, ledger.c.posting_date >= start, ledger.c.posting_date <= end)
            .order_by(ledger.c.account, ledger.c.posting_date, ledger.c.creation, ledger.c.name)
            .limit(MAX_ROWS + 1)
        ).mappings().all()
        setting = conn.execute(select(settings.c.base_currency).limit(1)).first()
    if len(rows) > MAX_ROWS:
        throw(f"More than {MAX_ROWS:,} ledger entries were found. Narrow the date range or select a specific account.")
    currency = setting[0] if setting else ""
    title_parts = [x for x in (account, party) if x]
    if account_from or account_to:
        title_parts.append(f"Account range {account_from or 'first'} to {account_to or 'last'}")
    rb = ReportBuilder(
        "Account Ledger — " + " / ".join(title_parts),
        [
            Column("account", "Account"),
            Column("posting_date", "Posting Date", "Date"),
            Column("transaction_date", "Transaction Date", "Date"),
            Column("due_date", "Due Date", "Date"),
            Column("value_date", "Value Date", "Date"),
            Column("source", "Source Document"),
            Column("source_line", "Source Line"),
            Column("posting_batch", "Posting Batch"),
            Column("external_reference", "External Reference"),
            Column("account_group_snapshot", "Account Group at Posting"),
            Column("root_type_snapshot", "Account Class at Posting"),
            Column("party", "Party"),
            Column("cost_centre", "Cost Centre"),
            Column("dimensions", "Accounting Dimensions"),
            Column("branch", "Branch"),
            Column("business_unit", "Business Unit"),
            Column("project", "Project"),
            Column("item", "Item"),
            Column("warehouse", "Warehouse"),
            Column("asset", "Fixed Asset"),
            Column("description", "Description"),
            Column("tax_code", "Tax Code"),
            Column("tax_jurisdiction", "Tax Jurisdiction"),
            Column("tax_rate", "Tax Rate (%)", "Float", total="none"),
            Column("taxable_amount", "Taxable Amount (Txn)", "Currency"),
            Column("tax_amount", "Tax Amount (Txn)", "Currency"),
            Column("base_taxable_amount", "Taxable Amount (Base)", "Currency"),
            Column("base_tax_amount", "Tax Amount (Base)", "Currency"),
            Column("settlement_reference", "Settlement Reference"),
            Column("currency", "Txn Currency"),
            Column("exchange_rate", "Rate", "Float", total="none"),
            Column("debit", "Debit (Txn)", "Currency"),
            Column("credit", "Credit (Txn)", "Currency"),
            Column("base_debit", "Debit (Base)", "Currency"),
            Column("base_credit", "Credit (Base)", "Currency"),
            Column("balance", "Running Balance", "Currency", total="none"),
        ],
        subtitle=f"{start:%d %b %Y} to {end:%d %b %Y}",
        currency=currency,
    )
    opening_by_account = {
        row["account"]: Decimal(str(row["debit"] or 0)) - Decimal(str(row["credit"] or 0))
        for row in opening_rows
    }
    account_order = sorted(set(opening_by_account) | {entry["account"] for entry in rows} | ({account} if account else set()))
    account_labels = {}
    for entry in rows:
        code = entry.get("account_code_snapshot") or entry["account_code"]
        name = entry.get("account_name_snapshot") or entry["account_name"]
        account_labels[entry["account"]] = f"{code} · {name}"
    if account_order:
        with db.transaction() as conn:
            labels = conn.execute(select(accounts.c.name, accounts.c.account_code, accounts.c.account_name).where(accounts.c.name.in_(account_order))).all()
        for label in labels:
            account_labels[label[0]] = f"{label[1]} · {label[2]}"
    total_debit = total_credit = Decimal(0)

    def add_entry(entry, balance):
        base_debit = Decimal(str(entry["base_debit"] or 0))
        base_credit = Decimal(str(entry["base_credit"] or 0))
        balance += base_debit - base_credit
        rb.row({
            "posting_date": entry["posting_date"].isoformat(),
            "transaction_date": entry["transaction_date"].isoformat() if entry.get("transaction_date") else None,
            "due_date": entry["due_date"].isoformat() if entry.get("due_date") else None,
            "value_date": entry["value_date"].isoformat() if entry.get("value_date") else None,
            "source": f"{entry['source_doctype']} {entry['source_name']}",
            "source_line": entry.get("source_line_reference") or "",
            "posting_batch": entry.get("posting_batch") or "",
            "external_reference": entry.get("external_reference") or "",
            "account": account_labels.get(entry["account"], entry["account"]),
            "account_group_snapshot": entry.get("account_group_snapshot") or "",
            "root_type_snapshot": entry.get("root_type_snapshot") or "",
            "party": f"{entry['party_type']}: {entry['party']}" if entry["party"] else "",
            "cost_centre": entry.get("cost_centre") or "",
            "dimensions": entry.get("dimensions") or {},
            "branch": entry.get("branch") or "",
            "business_unit": entry.get("business_unit") or "",
            "project": entry.get("project") or "",
            "item": entry.get("item") or "",
            "warehouse": entry.get("warehouse") or "",
            "asset": entry.get("asset") or "",
            "description": entry["line_description"] or "",
            "tax_code": entry.get("tax_code") or "",
            "tax_jurisdiction": entry.get("tax_jurisdiction") or "",
            "tax_rate": float(entry.get("tax_rate") or 0),
            "taxable_amount": Decimal(str(entry.get("taxable_amount") or 0)) or None,
            "tax_amount": Decimal(str(entry.get("tax_amount") or 0)) or None,
            "base_taxable_amount": Decimal(str(entry.get("base_taxable_amount") or 0)) or None,
            "base_tax_amount": Decimal(str(entry.get("base_tax_amount") or 0)) or None,
            "settlement_reference": entry.get("settlement_reference") or "",
            "currency": entry["currency"],
            "exchange_rate": float(entry["exchange_rate"] or 1),
            "debit": Decimal(str(entry["debit"] or 0)) or None,
            "credit": Decimal(str(entry["credit"] or 0)) or None,
            "base_debit": base_debit or None,
            "base_credit": base_credit or None,
            "balance": balance,
        })
        return balance

    rows_by_account = {}
    for entry in rows:
        rows_by_account.setdefault(entry["account"], []).append(entry)
    closing_by_account = {}
    for account_name in account_order:
        opening = opening_by_account.get(account_name, Decimal(0))
        if not account and len(account_order) > 1:
            rb.section(account_labels.get(account_name, account_name))
        rb.row({"account": account_labels.get(account_name, account_name), "description": "Opening Balance", "balance": opening})
        balance = opening
        for entry in rows_by_account.get(account_name, []):
            base_debit = Decimal(str(entry["base_debit"] or 0))
            base_credit = Decimal(str(entry["base_credit"] or 0))
            total_debit += base_debit
            total_credit += base_credit
            balance = add_entry(entry, balance)
        closing_by_account[account_name] = balance
        if not account and len(account_order) > 1:
            rb.row({"account": account_labels.get(account_name, account_name), "description": "Closing Balance", "balance": balance})
            rb.subtotal(f"Account Total — {account_labels.get(account_name, account_name)}")
    if account or len(account_order) == 1:
        sole_account = account or account_order[0]
        rb.row({"description": "Period Totals / Closing Balance", "base_debit": total_debit, "base_credit": total_credit, "balance": closing_by_account.get(sole_account, opening_by_account.get(sole_account, Decimal(0)))})
    else:
        rb.row({"description": "Party Period Totals (running balances are maintained separately by account)", "base_debit": total_debit, "base_credit": total_credit})
    return rb
