from velora import Document, throw


class FixedAssetHistoryLog(Document):
    def before_insert(self):
        if not getattr(self.flags, "trusted_source", False):
            throw("Fixed Asset History Logs can only be created by trusted asset lifecycle transactions.")

    def validate(self):
        if self._old:
            throw("Fixed Asset History Logs are immutable.")

    def before_delete(self):
        throw("Fixed Asset History Logs cannot be deleted.")
