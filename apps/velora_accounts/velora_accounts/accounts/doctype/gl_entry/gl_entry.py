from velora import Document, throw


class GLEntry(Document):
    """The ledger. Rows are written only by velora_accounts.ledger; they are never edited or deleted."""

    def validate(self):
        if not self.is_new():
            throw("Ledger entries cannot be edited. Cancel the source document to post a reversal.")

    def before_delete(self):
        throw("Ledger entries cannot be deleted. Cancel the source document to post a reversal.")
