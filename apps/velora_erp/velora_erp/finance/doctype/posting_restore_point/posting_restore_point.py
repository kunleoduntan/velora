from velora import Document, throw


class PostingRestorePoint(Document):
    def before_insert(self):
        if not getattr(self.flags, "trusted_source", False):
            throw("Restore points are written by the system only.")
