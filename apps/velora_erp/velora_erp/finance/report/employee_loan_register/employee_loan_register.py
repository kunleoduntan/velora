from velora import get_list, throw
from velora.reporting import Column, ReportBuilder
from velora.permissions import check_permission
from velora.meta.registry import registry

def execute(filters):
    filters=filters or {}; check_permission(registry.get("Employee Loan"),"read")
    rows=get_list("Employee Loan",filters={"docstatus":1},fields=["name","employee","loan_date","principal_amount","annual_interest_rate","term_months","total_interest","total_repayment","outstanding_principal","status"],limit=5001,ignore_permissions=True)
    if len(rows)>5000: throw("More than 5,000 employee loans were found.")
    rows=[x for x in rows if (not filters.get("employee") or x["employee"]==filters["employee"]) and (not filters.get("status") or x["status"]==filters["status"])]
    rb=ReportBuilder("Employee Loan Register",[Column("loan","Employee Loan","Link"),Column("employee","Employee","Link"),Column("loan_date","Loan Date","Date"),Column("principal_amount","Principal","Currency"),Column("annual_interest_rate","Annual Rate (%)","Float",total="none"),Column("term_months","Term (Months)","Int",total="none"),Column("total_interest","Total Interest","Currency"),Column("total_repayment","Total Repayment","Currency"),Column("outstanding_principal","Outstanding Principal","Currency"),Column("status","Status")])
    for x in rows: rb.row({"loan":x["name"],"employee":x["employee"],"loan_date":x["loan_date"],"principal_amount":x["principal_amount"],"annual_interest_rate":x["annual_interest_rate"],"term_months":x["term_months"],"total_interest":x["total_interest"],"total_repayment":x["total_repayment"],"outstanding_principal":x["outstanding_principal"],"status":x["status"]})
    rb.total("TOTAL"); return rb.build(filters=[("Employee",filters.get("employee") or "All"),("Status",filters.get("status") or "All")])
