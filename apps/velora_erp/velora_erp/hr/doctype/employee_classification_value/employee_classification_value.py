from velora import Document, get_doc, get_list, throw

class EmployeeClassificationValue(Document):
    def validate(self):
        self.value_code = str(self.value_code or "").strip().upper()
        self.value_name = str(self.value_name or "").strip()
        if not self.value_code or not self.value_name or not self.category:
            throw("Value Code, Value Name and Classification Category are required.")
        category = get_doc("Employee Classification Category", self.category, ignore_permissions=True)
        if category.disabled:
            throw("A disabled Classification Category cannot receive new values.")
        rows = get_list("Employee Classification Value", filters={"category": self.category}, fields=["name", "value_name"], limit=1000, ignore_permissions=True)
        for row in rows:
            if row.get("name") != getattr(self, "name", None) and str(row.get("value_name") or "").strip().casefold() == self.value_name.casefold():
                throw("Classification Value Name must be unique within its Category.")
