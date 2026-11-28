from decimal import Decimal
from velora import Document, throw


class BankStatementLine(Document):
    def validate(self):
        if Decimal(str(self.amount or 0)) <= 0:
            throw("A bank statement line amount must be greater than zero; the direction says whether it is a receipt or a payment.")

    def before_delete(self):
        if self.reconciliation or self.status in ("Matched", "Suggested"):
            throw("Unmatch the line before deleting it. Lines locked by a submitted reconciliation cannot be deleted.")
