from velora import Document, throw
class Warehouse(Document):
    def validate(self):
        if not self.warehouse_name:
            throw("Warehouse Name is required.")
        if self.parent_warehouse == self.name:
            throw("A Warehouse cannot be its own parent.")
