"""Seed the configurable standard Account Types for existing VeloraERP company databases."""
from velora_erp.setup import ensure_account_types


def execute():
    ensure_account_types()
