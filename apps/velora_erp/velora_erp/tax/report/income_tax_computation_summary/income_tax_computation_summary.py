from velora import get_list
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access

MONEY = ["accounting_profit", "total_add_backs", "total_deductions", "total_capital_allowances", "adjusted_profit", "loss_relieved", "assessable_profit", "loss_carried_forward",
         "income_tax_charge", "levies", "wht_utilised", "net_payable"]
LABEL = {"accounting_profit": "Profit per Books", "total_add_backs": "Add Backs", "total_deductions": "Deductions", "total_capital_allowances": "Capital Allowances", "adjusted_profit": "Adjusted Profit",
         "loss_relieved": "Loss Relieved", "assessable_profit": "Assessable Profit", "loss_carried_forward": "Loss C/F", "income_tax_charge": "Income Tax", "levies": "Levies", "wht_utilised": "WHT Credit Used",
         "net_payable": "Net Payable"}


def execute(filters):
    check_access()
    flt = [["docstatus", "=", 1]]
    if (filters or {}).get("jurisdiction"):
        flt.append(["jurisdiction", "=", filters["jurisdiction"]])
    rows = get_list("Income Tax Computation", filters=flt, fields=["name", "title", "jurisdiction", "period_start", "period_end"] + MONEY, order_by="period_end desc", limit=500)
    rb = ReportBuilder("Income Tax Computation Summary", [Column("name", "Computation"), Column("period_start", "From", "Date"), Column("period_end", "To", "Date")] + [Column(k, LABEL[k], "Currency") for k in MONEY])
    for r in rows:
        rb.row({**r, **{k: float(r[k] or 0) for k in MONEY}})
    return rb
