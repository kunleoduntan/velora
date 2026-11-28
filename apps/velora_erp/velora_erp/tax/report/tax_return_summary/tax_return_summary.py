from velora import get_list
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access


def execute(filters):
    check_access()
    f = filters or {}
    flt = [["docstatus", "!=", 2]]
    for k, op, fld in (("from_date", ">=", "period_start"), ("to_date", "<=", "period_end"), ("tax_type", "=", "tax_type"), ("return_status", "=", "return_status")):
        if f.get(k): flt.append([fld, op, f[k]])
    rows = get_list("Tax Return", filters=flt, fields=["name", "tax_type", "jurisdiction", "period_start", "period_end", "return_status", "approval_status", "output_tax", "input_tax", "non_recoverable_tax", "net_payable", "filing_reference"], order_by="period_end desc", limit=5000)
    rb = ReportBuilder("Tax Return Summary", [Column("name", "Return"), Column("tax_type", "Tax"), Column("jurisdiction", "Jurisdiction"), Column("period_start", "From", "Date"), Column("period_end", "To", "Date"),
        Column("return_status", "Status"), Column("approval_status", "Approval"), Column("output_tax", "Output Tax", "Currency"), Column("input_tax", "Input Tax", "Currency"),
        Column("non_recoverable_tax", "Not Recoverable", "Currency"), Column("net_payable", "Payable / (Refundable)", "Currency"), Column("filing_reference", "Filing Ref")])
    tot = 0.0
    for r in rows:
        rb.row(r); tot += float(r.get("net_payable") or 0)
    rb.row({"name": "Total", "net_payable": round(tot, 2)})
    return rb
