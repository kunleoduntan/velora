"""Add universal cash management and recognition schedules to Finance workspace."""
from velora_erp.setup import ensure_finance_workspace


def execute():
    ensure_finance_workspace()
