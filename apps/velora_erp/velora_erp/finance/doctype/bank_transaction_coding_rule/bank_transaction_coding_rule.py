from velora import Document, throw
from velora_erp.finance.validation import row
class BankTransactionCodingRule(Document):
    def validate(self):
        if int(self.priority or 0)<1: throw("Priority must be a positive integer.")
        if not self.match_text or not self.match_text.strip(): throw("Match Text is required.")
        account=row("Account",self.offset_account,"name","disabled")
        if not account or account["disabled"]: throw("Select an active Offset Account.")
        if self.party_type and not self.party: throw("Party is required when Party Type is selected.")
        if self.valid_from and self.valid_to and str(self.valid_to)<str(self.valid_from): throw("Valid To cannot be earlier than Valid From.")
