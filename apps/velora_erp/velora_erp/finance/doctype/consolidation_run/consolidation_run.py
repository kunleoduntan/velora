from velora import Document, throw


class ConsolidationRun(Document):
    def validate(self):
        if self._old:
            throw("A saved consolidation is a record of what was reported and cannot be changed; run it again instead")
        if not self.from_date or not self.to_date or str(self.from_date) > str(self.to_date):
            throw("The start date must not be after the end date")
