from datetime import date
from velora import get_list, throw
from velora.reporting import Column, ReportBuilder
from velora.permissions import check_permission
from velora.meta.registry import registry

def execute(filters):
    filters=filters or {}; start=filters.get("from_date"); end=filters.get("to_date") or date.today(); employee=filters.get("employee")
    if start and start>end: throw("From Date cannot be after To Date.")
    check_permission(registry.get("Salary Slip"),"read")
    slips=get_list("Salary Slip",filters={"docstatus":1},fields=["name","employee","payroll_run","period_start","period_end","gross_earnings","employee_deductions","loan_repayments","advance_recoveries","employer_contributions","tax_credit_amount","net_pay","paid_amount","outstanding_amount","status"],limit=5001,ignore_permissions=True)
    if len(slips)>5000: throw("More than 5,000 salary slips were found. Narrow the report filters.")
    slips=[x for x in slips if (not start or str(x["period_end"])[:10]>=str(start)[:10]) and str(x["period_start"])[:10]<=str(end)[:10] and (not employee or x["employee"]==employee)]
    rb=ReportBuilder("Payroll Register",[Column("employee","Employee","Link"),Column("salary_slip","Salary Slip","Link"),Column("payroll_run","Payroll Run","Link"),Column("period_start","Period Start","Date"),Column("period_end","Period End","Date"),Column("gross_earnings","Gross Earnings","Currency"),Column("employee_deductions","Employee Deductions","Currency"),Column("loan_repayments","Loan Repayments","Currency"),Column("advance_recoveries","Advance Recoveries","Currency"),Column("employer_contributions","Employer Contributions","Currency"),Column("tax_credit_amount","Approved PAYE Refund / Credit","Currency"),Column("net_pay","Net Pay","Currency"),Column("paid_amount","Paid","Currency"),Column("outstanding_amount","Outstanding","Currency"),Column("status","Status")])
    for x in slips: rb.row({"employee":x["employee"],"salary_slip":x["name"],"payroll_run":x["payroll_run"],"period_start":x["period_start"],"period_end":x["period_end"],"gross_earnings":x["gross_earnings"],"employee_deductions":x["employee_deductions"],"loan_repayments":x["loan_repayments"],"advance_recoveries":x["advance_recoveries"],"employer_contributions":x["employer_contributions"],"tax_credit_amount":x.get("tax_credit_amount",0),"net_pay":x["net_pay"],"paid_amount":x["paid_amount"],"outstanding_amount":x["outstanding_amount"],"status":x["status"]})
    rb.total("TOTAL")
    return rb.build(filters=[("From Date",start or "All"),("To Date",end),("Employee",employee or "All")],notes=["Payroll calculations are shown from posted Salary Slips only.","Approved PAYE refund credits are shown separately from current-period deductions; payroll payments settle the resulting net salary liability independently."])
