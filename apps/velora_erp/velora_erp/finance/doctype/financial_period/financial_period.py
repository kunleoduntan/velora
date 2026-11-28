from velora import Document, get_doc, get_list, throw


class FinancialPeriod(Document):
    def validate(self):
        if not self.period_name or not self.period_name.strip():
            throw("Period Name is required.")
        if self.period_number is None or not 1 <= int(self.period_number) <= 99:
            throw("Period Number must be between 1 and 99.")
        if not self.start_date or not self.end_date:
            throw("Both Start Date and End Date are required.")
        if self.end_date < self.start_date:
            throw("End Date cannot be earlier than Start Date.")
        year = get_doc("Financial Year", self.financial_year, ignore_permissions=True)
        if self.start_date < year.start_date or self.end_date > year.end_date:
            throw("The Financial Period dates must fall within the selected Financial Year.")
        siblings = get_list("Financial Period", filters=[["financial_year", "=", self.financial_year]], fields=["name", "period_number", "start_date", "end_date"], limit=1000, ignore_permissions=True)
        for row in siblings:
            if row["name"] == self.name:
                continue
            if int(row["period_number"]) == int(self.period_number):
                throw(f"Period Number {self.period_number} is already used in Financial Year {self.financial_year}.")
            if self.start_date <= row["end_date"] and self.end_date >= row["start_date"]:
                throw(f"This date range overlaps Financial Period {row['name']}.")
        if year.status == "Closed" and self.status != "Closed":
            throw("A period belonging to a closed Financial Year must also be closed.")
        old = getattr(self, "_old", None) or {}
        if self.status == "Closed" and old.get("status") != "Closed":
            throw("Financial Periods must be closed through an approved Financial Period Close document.")
        if self.status == "Closed" and not self.closed_on:
            throw("A closed Financial Period must have a Closed On date.")
