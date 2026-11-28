from velora_erp.finance.reporting_provider import check_access
from velora_erp.treasury.reports import run


def execute(filters):
    check_access()
    return run("Borrowing Cost by Lender", filters or {})
