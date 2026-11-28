from velora import Document, throw


class AccountingDimension(Document):
    def validate(self):
        self.dimension_code = (self.dimension_code or "").strip().upper()
        self.dimension_name = (self.dimension_name or "").strip()
        if not self.dimension_code or not self.dimension_name:
            throw("Dimension code and name are required")
        # Master-backed values are resolved against installed DocTypes when a transaction is validated.
        # This allows a dimension to be configured before an optional industry/master-data app is installed.
