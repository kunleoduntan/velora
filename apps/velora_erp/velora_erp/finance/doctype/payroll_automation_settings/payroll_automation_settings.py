from velora import Document, throw


class PayrollAutomationSettings(Document):
    def validate(self):
        for f in ("rent_relief_rate", "basic_percent_of_gross"):
            v = getattr(self, f, None)
            if v not in (None, "") and not 0 <= float(v) <= 100:
                throw("Percentages must be between 0 and 100.")
        if float(getattr(self, "rent_relief_cap", 0) or 0) < 0:
            throw("Rent Relief Cap cannot be negative.")
