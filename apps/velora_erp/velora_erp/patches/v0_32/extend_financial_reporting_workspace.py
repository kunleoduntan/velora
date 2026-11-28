from velora_erp.setup import ensure_finance_workspace, ensure_period_end_workspace


def execute():
    ensure_finance_workspace()
    ensure_period_end_workspace()
