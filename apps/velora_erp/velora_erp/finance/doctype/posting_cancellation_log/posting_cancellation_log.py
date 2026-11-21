from velora import Document, throw


class PostingCancellationLog(Document):
    """Cancellation evidence. Created by finance.cancellation only; never edited or deleted."""

    def before_insert(self):
        if not getattr(self.flags, "trusted_source", False):
            throw("Posting Cancellation Logs are written by the system when a document is cancelled.")

    def validate(self):
        if self._old:
            throw("Posting Cancellation Logs cannot be changed.")

    def before_delete(self):
        throw("Posting Cancellation Logs cannot be deleted.")
