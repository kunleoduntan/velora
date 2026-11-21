from velora import Document, throw
class Batch(Document):
    def validate(self):
        if not self.item_code or not self.batch_number:
            throw("Inventory Item and Batch Number are required.")
        if self.manufacturing_date and self.expiry_date and self.expiry_date < self.manufacturing_date:
            throw("Batch Expiry Date cannot be earlier than Manufacturing Date.")
