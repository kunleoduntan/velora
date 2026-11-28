from velora import Document, throw


class AccountLedgerRecord(Document):
    """Append-only account ledger row; only the trusted posting engine may create it."""

    def before_insert(self):
        if not getattr(self.flags, "posting_engine_authorized", False):
            throw("Account Ledger Records can only be created by the Financial Posting Engine.")

    def validate(self):
        if not self.is_new():
            throw("Account Ledger Records are immutable. Use a controlled reversal to correct a posted transaction.")
        if not getattr(self.flags, "posting_engine_authorized", False):
            throw("Account Ledger Records can only be created by the Financial Posting Engine.")

    def before_delete(self):
        throw("Account Ledger Records cannot be deleted. Use a controlled reversal to correct a posted transaction.")
