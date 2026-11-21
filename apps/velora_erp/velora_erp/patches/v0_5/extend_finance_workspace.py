"""Add Customer, Supplier and statement shortcuts to existing Finance workspaces."""
from velora_erp.setup import ensure_finance_workspace


def execute():
    ensure_finance_workspace()
