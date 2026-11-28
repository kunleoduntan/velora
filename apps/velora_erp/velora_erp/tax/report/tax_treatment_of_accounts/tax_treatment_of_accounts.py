from velora import throw
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.tax.cit import profit_and_loss


def execute(filters):
    check_access()
    f = filters or {}
    if not f.get("from_date") or not f.get("to_date"):
        throw("From Date and To Date are required.")
    rb = ReportBuilder("Tax Treatment of Accounts", [Column("account", "Account"), Column("name", "Name"), Column("root_type", "Type"), Column("treatment", "Tax Treatment"),
                                                     Column("percent", "Not Allowed %", "Float"), Column("net", "Balance in Period", "Currency"), Column("adjustment", "Tax Adjustment", "Currency")])
    total = 0.0
    for x in profit_and_loss(f["from_date"], f["to_date"]):
        net = float(x["net"])
        adj = net if x["treatment"] in ("Not tax allowed", "Capital (use capital allowance)") else net * float(x["percent"]) / 100 if x["treatment"] == "Partly allowable" else -net if x["treatment"] == "Exempt income" else 0.0
        total += adj
        rb.row({**x, "percent": float(x["percent"]), "net": net, "adjustment": round(adj, 2)})
    rb.row({"name": "Net adjustment to profit", "adjustment": round(total, 2)})
    return rb
