"""Expose Sales/Purchase Returns and Landed Cost in company workspaces."""
from velora_erp.setup import ensure_commercial_workspaces

def execute():
    ensure_commercial_workspaces()
