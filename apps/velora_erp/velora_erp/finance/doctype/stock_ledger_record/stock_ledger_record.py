from velora import Document, throw

class StockLedgerRecord(Document):
    def before_insert(self):
        if not getattr(self.flags, "inventory_engine_authorized", False):
            throw("Stock Ledger Records can only be created by the Inventory Engine.")
    def validate(self):
        if not self.is_new() or not getattr(self.flags, "inventory_engine_authorized", False):
            throw("Stock Ledger Records are immutable and engine-controlled.")
    def before_delete(self):
        throw("Stock Ledger Records cannot be deleted. Correct stock through a new adjustment.")
