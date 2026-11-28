from sqlalchemy import select
from velora import db, throw
from velora.db.tables import get_table
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access


def execute(filters):
    check_access()
    f = filters or {}
    if not f.get("from_date") or not f.get("to_date"):
        throw("From Date and To Date are required.")
    h, l = get_table("Tax Journal"), get_table("Tax Journal Line")
    q = (select(h.c.name, h.c.posting_date, l.c.party_type, l.c.party, l.c.nature, l.c.payee_class, l.c.party_name, l.c.invoice_reference, l.c.tax_rule, l.c.rate, l.c.gross_amount, l.c.wht_amount, l.c.certificate_number, l.c.certificate_date)
         .join(l, l.c.parent == h.c.name).where(h.c.docstatus == 1, h.c.posting_date >= f["from_date"], h.c.posting_date <= f["to_date"]))
    if f.get("party_type"):
        q = q.where(l.c.party_type == f["party_type"])
    if f.get("party"):
        q = q.where(l.c.party == f["party"])
    if f.get("missing_certificate"):
        q = q.where((l.c.certificate_number.is_(None)) | (l.c.certificate_number == ""))
    with db.transaction() as c:
        rows = c.execute(q.order_by(h.c.posting_date, h.c.name)).mappings().all()
    rb = ReportBuilder("WHT Register", [Column("posting_date", "Date", "Date"), Column("name", "Tax Journal"), Column("direction", "Direction"), Column("party", "Party"), Column("party_name", "Name"),
                                        Column("nature", "Nature"), Column("payee_class", "Payee / Payer"), Column("invoice_reference", "Invoice"), Column("tax_rule", "Rule"), Column("rate", "Rate %", "Float"), Column("gross_amount", "Taxable Amount", "Currency"),
                                        Column("wht_amount", "Tax Withheld", "Currency"), Column("certificate_number", "Certificate"), Column("certificate_date", "Certificate Date", "Date")])
    tot = {"Customer": 0.0, "Supplier": 0.0, "Income received": 0.0, "Payment made": 0.0}
    for r in rows:
        d = dict(r); d["direction"] = "Suffered - credit to us" if r["party_type"] in ("Customer", "Income received") else "Withheld by us - payable"
        d["gross_amount"], d["wht_amount"] = float(r["gross_amount"] or 0), float(r["wht_amount"] or 0)
        tot[r["party_type"]] += d["wht_amount"]
        rb.row(d)
    rb.row({"direction": "Total suffered (credits)", "wht_amount": round(tot["Customer"] + tot["Income received"], 2)})
    rb.row({"direction": "Total withheld by us (payable)", "wht_amount": round(tot["Supplier"] + tot["Payment made"], 2)})
    return rb
