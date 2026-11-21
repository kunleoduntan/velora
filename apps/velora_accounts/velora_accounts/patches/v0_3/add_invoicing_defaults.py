"""Existing companies: add the Discount accounts, the default accounts (incl. Prepayments from 0.2), the VAT tax codes that invoicing needs, and a
Customer/Supplier master record for every party that already has postings. Only adds what is missing; never changes a default you already chose."""
from velora_accounts.seed import ensure_invoicing_setup


def execute():
    ensure_invoicing_setup()
