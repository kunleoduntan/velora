"""Add portable composite indexes for high-volume account ledger access."""
from sqlalchemy import Index

from velora import db
from velora.db.tables import get_table


def execute():
    ledger = get_table("Account Ledger Record")
    indexes = [
        Index("ix_velora_ledger_account_date", ledger.c.account, ledger.c.posting_date),
        Index("ix_velora_ledger_period_account", ledger.c.financial_period, ledger.c.account),
        Index("ix_velora_ledger_source", ledger.c.source_doctype, ledger.c.source_name),
        Index("ix_velora_ledger_party_date", ledger.c.party_type, ledger.c.party, ledger.c.posting_date),
        Index("ix_velora_ledger_cost_date", ledger.c.cost_centre, ledger.c.posting_date),
    ]
    with db.transaction() as conn:
        for index in indexes:
            index.create(bind=conn, checkfirst=True)
