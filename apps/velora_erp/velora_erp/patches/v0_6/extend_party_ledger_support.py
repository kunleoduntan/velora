"""Refresh Finance workspace shortcuts for Customer, Supplier and Employee ledgers."""
from velora_erp.setup import ensure_finance_workspace


def execute():
    ensure_finance_workspace()
