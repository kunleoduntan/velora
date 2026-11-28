from velora import get_list, throw
from velora.reporting import Column, ReportBuilder
from velora.permissions import check_permission
from velora.meta.registry import registry

def execute(filters):
    filters=filters or {}; check_permission(registry.get("Employee Advance"),"read")
    rows=get_list("Employee Advance",filters={"docstatus":1},fields=["name","employee","advance_date","purpose","amount","currency","expected_settlement_date","outstanding_amount","status"],limit=5001,ignore_permissions=True)
    if len(rows)>5000: throw("More than 5,000 employee advances were found.")
    rows=[x for x in rows if (not filters.get("employee") or x["employee"]==filters["employee"]) and (not filters.get("status") or x["status"]==filters["status"])]
    rb=ReportBuilder("Employee Advance Register",[Column("advance","Employee Advance","Link"),Column("employee","Employee","Link"),Column("advance_date","Advance Date","Date"),Column("purpose","Purpose"),Column("amount","Advance Amount","Currency"),Column("currency","Currency"),Column("expected_settlement_date","Expected Settlement","Date"),Column("outstanding_amount","Outstanding","Currency"),Column("status","Status")])
    for x in rows: rb.row({"advance":x["name"],"employee":x["employee"],"advance_date":x["advance_date"],"purpose":x["purpose"],"amount":x["amount"],"currency":x["currency"],"expected_settlement_date":x["expected_settlement_date"],"outstanding_amount":x["outstanding_amount"],"status":x["status"]})
    rb.total("TOTAL"); return rb.build(filters=[("Employee",filters.get("employee") or "All"),("Status",filters.get("status") or "All")])
