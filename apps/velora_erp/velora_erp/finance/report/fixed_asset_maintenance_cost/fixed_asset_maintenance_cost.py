from decimal import Decimal

from sqlalchemy import select

from velora import db, get_list
from velora.db.tables import get_table
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access


def execute(filters=None):
    """Expense lines tagged to an asset (Purchase Invoice / Journal Entry 'Repair / Maintenance of Asset'), grouped per asset."""
    check_access()
    f = filters or {}
    ledger = get_table("Account Ledger Record")
    expense = [a["name"] for a in get_list("Account", filters={"root_type": "Expense"}, fields=["name"], limit=100000, ignore_permissions=True)]
    q = select(ledger).where(ledger.c.asset.isnot(None), ledger.c.asset != "", ledger.c.account.in_(expense or [""]),
                          ledger.c.source_doctype.in_(["Purchase Invoice", "Journal Entry Voucher"]))   # not depreciation / impairment
    if f.get("asset"):
        q = q.where(ledger.c.asset == f["asset"])
    if f.get("from_date"):
        q = q.where(ledger.c.posting_date >= f["from_date"])
    if f.get("to_date"):
        q = q.where(ledger.c.posting_date <= f["to_date"])
    q = q.order_by(ledger.c.asset, ledger.c.posting_date)
    with db.transaction() as conn:
        rows = conn.execute(q).mappings().all()
    rb = ReportBuilder("Fixed Asset Maintenance Cost", [
        Column("asset", "Asset / Voucher", "Data"), Column("posting_date", "Date", "Date"), Column("account", "Expense Account", "Link"),
        Column("description", "Description", "Data"), Column("amount", "Cost", "Currency", total="sum")], currency="")
    current, first = None, True
    for r in rows:
        if r["asset"] != current:
            if current is not None:
                rb.subtotal(f"Total {current}")
            rb.section(r["asset"])
            current = r["asset"]
        rb.row({"asset": f"{r['source_doctype']} {r['source_name']}", "posting_date": r["posting_date"], "account": r["account"],
                "description": r.get("line_description") or "", "amount": Decimal(str(r["base_debit"] or 0)) - Decimal(str(r["base_credit"] or 0))}, indent=1)
    if current is not None:
        rb.subtotal(f"Total {current}")
        rb.total("TOTAL REPAIRS & MAINTENANCE")
    return rb
