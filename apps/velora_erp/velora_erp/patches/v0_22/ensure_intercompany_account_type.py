"""Add the dedicated Intercompany Receivable Account Type to existing companies."""
from velora_erp.setup import ensure_account_types


def execute():
    ensure_account_types()
