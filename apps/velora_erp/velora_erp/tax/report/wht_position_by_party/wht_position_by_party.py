from collections import defaultdict
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
    q = (select(l.c.party_type, l.c.party, l.c.party_name, l.c.gross_amount, l.c.wht_amount, l.c.certificate_number)
         .join(h, l.c.parent == h.c.name).where(h.c.docstatus == 1, h.c.posting_date >= f["from_date"], h.c.posting_date <= f["to_date"]))
    with db.transaction() as c:
        rows = c.execute(q).mappings().all()
    agg = defaultdict(lambda: {"rows": 0, "gross": 0.0, "wht": 0.0, "missing": 0})
    for r in rows:
        a = agg[(r["party_type"], r["party"], r["party_name"])]
        a["rows"] += 1; a["gross"] += float(r["gross_amount"] or 0); a["wht"] += float(r["wht_amount"] or 0); a["missing"] += 0 if r["certificate_number"] else 1
    rb = ReportBuilder("WHT Position by Party", [Column("party_type", "Type"), Column("party", "Party"), Column("party_name", "Name"), Column("rows", "Entries", "Int"),
                                                 Column("gross", "Taxable Amount", "Currency"), Column("wht", "Tax Withheld", "Currency"), Column("missing", "Certificates Missing", "Int")])
    for (pt, p, n), a in sorted(agg.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        rb.row({"party_type": pt, "party": p, "party_name": n, "rows": a["rows"], "gross": round(a["gross"], 2), "wht": round(a["wht"], 2), "missing": a["missing"]})
    return rb
