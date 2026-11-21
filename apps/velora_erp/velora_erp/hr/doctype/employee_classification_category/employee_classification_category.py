from velora import Document, throw

class EmployeeClassificationCategory(Document):
    def validate(self):
        self.category_code = str(self.category_code or "").strip().upper()
        self.category_name = str(self.category_name or "").strip()
        if not self.category_code or not self.category_name:
            throw("Category Code and Category Name are required.")
