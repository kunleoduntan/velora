from velora import throw
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.tax.service import ledger_rows


def execute(filters):
    check_access()
    f = filters or {}
    if not f.get("from_date") or not f.get("to_date"):
        throw("From Date and To Date are required.")
    if str(f["from_date"]) > str(f["to_date"]):
        throw("From Date cannot be after To Date.")
    rows = ledger_rows(f["from_date"], f["to_date"], f.get("tax_code"))
    if f.get("section"):
        rows = [r for r in rows if r["section"] == f["section"]]
    rb = ReportBuilder("Tax Ledger", [Column("date", "Date", "Date"), Column("section", "Section"), Column("tax_code", "Tax Code"), Column("tax_rate", "Rate %", "Float"),
                                      Column("source_doctype", "Document Type"), Column("source_name", "Document"), Column("party", "Party"),
                                      Column("net", "Net Amount", "Currency"), Column("tax", "Tax", "Currency")])
    out = inp = 0.0
    for r in rows:
        rb.row({**r, "net": float(r["net"]), "tax": float(r["tax"])})
        if r["section"] == "Output tax": out += float(r["tax"])
        else: inp += float(r["tax"])
    rb.row({"section": "Total output tax", "tax": round(out, 2)})
    rb.row({"section": "Total input tax", "tax": round(inp, 2)})
    return rb
