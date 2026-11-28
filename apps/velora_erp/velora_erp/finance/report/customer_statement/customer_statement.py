from velora import throw
from velora_erp.finance.validation import row
from velora_erp.finance.report.account_ledger.account_ledger import execute as account_ledger


def execute(filters):
    party = (filters.get("customer") or "").strip()
    if not party:
        throw("Select a Customer to run the statement.")
    record = row("Customer", party, "name", "disabled")
    if not record or record["disabled"]:
        throw("Select an active Customer.")
    result = account_ledger({
        "party": party,
        "party_type": "Customer",
        "from_date": filters.get("from_date"),
        "to_date": filters.get("to_date"),
        "cost_centre": filters.get("cost_centre"),
        "account_from": filters.get("account_from"), "account_to": filters.get("account_to"),
    })
    result.title = "Customer Statement — " + party
    return result
