"""Add invoice entry points to the native Finance workspace."""
from velora_erp.setup import ensure_finance_workspace

def execute():
    ensure_finance_workspace()
