from velora import Document, get_list, throw

NAME = {"Customer": "customer_name", "Supplier": "supplier_name", "Employee": "employee_name"}


class PartyImportantDate(Document):
    def validate(self):
        rows = get_list(self.party_type, filters=[["name", "=", self.party]], fields=[NAME[self.party_type]], limit=1, ignore_permissions=True)
        if not rows:
            throw(f"{self.party_type} {self.party} does not exist.")
        self.party_name = rows[0][NAME[self.party_type]]
        if self.date_type == "Other" and not (self.label or "").strip():
            throw("Say what this date celebrates.")
        if not self.label:
            self.label = f"{self.date_type}: {self.party_name}"
