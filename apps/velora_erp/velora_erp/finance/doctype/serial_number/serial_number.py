from velora import Document, throw
class SerialNumber(Document):
    def validate(self):
        if not self.serial_number or not self.item_code:
            throw("Serial Number and Inventory Item are required.")
