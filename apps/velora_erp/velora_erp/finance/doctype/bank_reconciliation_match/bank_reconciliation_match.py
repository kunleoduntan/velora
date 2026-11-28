from velora import Document, throw


class BankReconciliationMatch(Document):
    def validate(self):
        if bool(self.statement_line) == bool(self.ledger_record) and not (self.statement_line and self.ledger_record):
            throw("A match row must link a bank statement line or a ledger entry.")

    def before_delete(self):
        if self.reconciliation:
            throw("This match is locked by a submitted bank reconciliation.")
