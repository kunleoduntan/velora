"""VAT (sales tax) return: output tax from sales less returns, input tax from purchases less returns, and the balance to pay or recover."""
from decimal import Decimal

from sqlalchemy import select

from velora import db, throw
from velora.db.tables import get_table
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access

ZERO = Decimal("0")
# (section, parent doctype, line doctype, sign)  - sales and purchase returns reduce what they reverse
SOURCES = (("Output tax (sales)", "Sales Invoice", "Sales Invoice Line", 1),
           ("Output tax (sales)", "Sales Return", "Sales Return Line", -1),
           ("Input tax (purchases)", "Purchase Invoice", "Purchase Invoice Line", 1),
           ("Input tax (purchases)", "Purchase Return", "Purchase Return Line", -1))


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def vat_rows(start, end) -> list[dict]:
    totals: dict[tuple, dict] = {}
    for section, parent, line, sign in SOURCES:
        p, l = get_table(parent), get_table(line)
        with db.transaction() as c:
            rows = c.execute(select(l.c.tax_code, l.c.tax_rate, l.c.amount, l.c.tax_amount, l.c.tax_account, p.c.exchange_rate)
                             .join(p, (l.c.parent == p.c.name) & (l.c.parenttype == parent))
                             .where(p.c.docstatus == 1, p.c.posting_date >= start, p.c.posting_date <= end)).all()
        for code, rate, amount, tax, account, fx in rows:
            if not account and not _d(tax):
                continue                                                   # an untaxed line is not part of the return
            if not _d(tax):                                                # invoices store the rate; the tax follows from it
                tax = (_d(amount) * _d(rate) / Decimal("100")).quantize(Decimal("0.01"))
            rate_fx = _d(fx) or Decimal("1")
            key = (section, code or "(no tax code)", _d(rate))
            row = totals.setdefault(key, {"section": section, "tax_code": key[1], "tax_rate": float(key[2]), "net": ZERO, "tax": ZERO})
            row["net"] += sign * _d(amount) * rate_fx
            row["tax"] += sign * _d(tax) * rate_fx
    return [{**r, "net": float(r["net"]), "tax": float(r["tax"])} for r in sorted(totals.values(), key=lambda r: (r["section"], r["tax_code"], r["tax_rate"]))]


def execute(filters):
    check_access()
    f = filters or {}
    start, end = f.get("from_date"), f.get("to_date")
    if not start or not end:
        throw("From Date and To Date are required for the VAT Return.")
    if str(start) > str(end):
        throw("From Date cannot be after To Date.")
    rows = vat_rows(start, end)
    rb = ReportBuilder("VAT Return", [Column("section", "Section"), Column("tax_code", "Tax Code"), Column("tax_rate", "Rate %", "Float"),
                                       Column("net", "Net Amount", "Currency"), Column("tax", "Tax", "Currency")])
    output = sum((r["tax"] for r in rows if r["section"].startswith("Output")), 0.0)
    inp = sum((r["tax"] for r in rows if r["section"].startswith("Input")), 0.0)
    for r in rows:
        rb.row(r)
    rb.row({"section": "Total output tax", "tax": output})
    rb.row({"section": "Total input tax", "tax": inp})
    rb.row({"section": "Tax payable" if output >= inp else "Tax refundable", "tax": abs(output - inp)})
    return rb
