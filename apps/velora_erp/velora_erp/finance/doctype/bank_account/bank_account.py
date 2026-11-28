from velora import Document, throw
from velora_erp.finance.validation import row


class BankAccount(Document):
    def validate(self):
        self.currency = (self.currency or "").strip().upper() or None
        if self.currency and (len(self.currency) != 3 or not self.currency.isalpha()):
            throw("Currency must be a three-letter ISO code such as USD or EUR.")
        gl = row("Account", self.gl_account, "name", "root_type", "account_type", "disabled", "reconciliation_required")
        if not gl or gl["disabled"] or gl["root_type"] != "Asset" or gl["account_type"] not in {"BANK", "CASH"}:
            throw("General Ledger Account must be an active Asset account of type Bank or Cash.")
        if not gl["reconciliation_required"]:
            throw(f"{self.gl_account} does not allow reconciliation. Tick Allow Reconciliation on that account, or choose another one.")
