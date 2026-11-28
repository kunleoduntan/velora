"""Create the integrated Finance workspace and starter financial statements once."""
from velora_erp.setup import ensure_finance_workspace, ensure_financial_statement_layouts


def execute():
    ensure_financial_statement_layouts()
    ensure_finance_workspace()
