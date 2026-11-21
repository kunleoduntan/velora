from velora import Document, get_list, throw


class FinancialYear(Document):
    def validate(self):
        if not self.year_name or not self.year_name.strip():
            throw("Financial Year is required.")
        if not self.start_date or not self.end_date:
            throw("Both Start Date and End Date are required.")
        if self.end_date < self.start_date:
            throw("End Date cannot be earlier than Start Date.")
        years = get_list("Financial Year", fields=["name", "start_date", "end_date", "is_current"], limit=1000, ignore_permissions=True)
        for row in years:
            if row["name"] == self.name:
                continue
            if self.start_date <= row["end_date"] and self.end_date >= row["start_date"]:
                throw(f"This date range overlaps Financial Year {row['name']}.")
            if self.is_current and row.get("is_current"):
                throw(f"Financial Year {row['name']} is already marked as the current year.")
        if self.status == "Closed":
            periods = get_list("Financial Period", filters=[["financial_year", "=", self.name]], fields=["name", "status"], limit=1000, ignore_permissions=True)
            if any(p["status"] != "Closed" for p in periods):
                throw("All Financial Periods must be closed before the Financial Year can be closed.")
        if self.status == "Closed" and not self.closing_date:
            # Closing workflow will set this date when the period-control service is implemented.
            throw("A closed Financial Year must have a Date Closed.")
