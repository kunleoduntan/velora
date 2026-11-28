from collections import defaultdict
from velora import throw
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.tax.service import ledger_rows, load_rules

SOURCE_LABEL = {"Tax Journal": "Tax Journal", "Investment Transaction": "Investment income", "Investment": "Investment income", "Receipt": "Receipt", "Payment": "Payment",
                "Sales Invoice": "Sales invoice", "Purchase Invoice": "Purchase invoice", "Journal Entry Voucher": "Journal"}


def execute(filters):
    check_access()
    f = filters or {}
    if not f.get("from_date") or not f.get("to_date"):
        throw("From Date and To Date are required.")
    codes = {r.code for r in load_rules(None, "WHT")}
    rb = ReportBuilder("WHT All Sources", [Column("date", "Date", "Date"), Column("direction", "Direction"), Column("source", "Source"), Column("source_doctype", "Document Type"), Column("source_name", "Document"),
                                           Column("party", "Party"), Column("tax_code", "Rule"), Column("tax_rate", "Rate %", "Float"), Column("net", "Taxable Amount", "Currency"), Column("tax", "Tax", "Currency")])
    totals, by_source = defaultdict(float), defaultdict(lambda: defaultdict(float))
    for r in ledger_rows(f["from_date"], f["to_date"]):
        if (r["tax_code"] or "").upper() not in codes:
            continue
        direction = "Payable (withheld by us)" if r["section"] == "Output tax" else "Credit suffered"
        source = SOURCE_LABEL.get(r["source_doctype"], r["source_doctype"] or "")
        if f.get("direction") and f["direction"] != direction:
            continue
        if f.get("source") and f["source"].lower() not in (r["source_doctype"] or "").lower():
            continue
        rb.row({"date": r["date"], "direction": direction, "source": source, "source_doctype": r["source_doctype"], "source_name": r["source_name"], "party": r["party"],
                "tax_code": r["tax_code"], "tax_rate": r["tax_rate"], "net": float(r["net"]), "tax": float(r["tax"])})
        totals[direction] += float(r["tax"]); by_source[direction][source] += float(r["tax"])
    for direction in ("Credit suffered", "Payable (withheld by us)"):
        for source, amount in sorted(by_source[direction].items()):
            rb.row({"direction": f"Total {direction.lower()}", "source": source, "tax": round(amount, 2)})
        rb.row({"direction": f"TOTAL {direction.upper()}", "tax": round(totals[direction], 2)})
    return rb
