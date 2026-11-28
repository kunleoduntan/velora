from velora import throw
from velora_erp.finance.validation import row
from velora_erp.finance.report.account_ledger.account_ledger import execute as account_ledger


def execute(filters):
    employee = (filters.get("employee") or "").strip()
    if not employee:
        throw("Select an Employee to run the Employee Ledger.")
    record = row("Employee", employee, "name", "disabled")
    if not record or record["disabled"]:
        throw("Select an active Employee.")
    result = account_ledger({
        "party": employee, "party_type": "Employee",
        "from_date": filters.get("from_date"), "to_date": filters.get("to_date"),
        "cost_centre": filters.get("cost_centre"),
        "account_from": filters.get("account_from"), "account_to": filters.get("account_to"),
    })
    result.title = "Employee Ledger — " + employee
    return result
