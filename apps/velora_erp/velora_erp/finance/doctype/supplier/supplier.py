from sqlalchemy import select
from velora import Document, throw, db
from velora.db.tables import get_table
from velora_erp.finance.validation import check_control_account, row


class Supplier(Document):
    def validate(self):
        self.supplier_code = (self.supplier_code or "").strip().upper()
        self.supplier_name = (self.supplier_name or "").strip()
        if not self.supplier_code or not self.supplier_name:
            throw("Supplier Code and Supplier Name are required.")
        group = row("Supplier Group", self.supplier_group, "name", "disabled", "is_group")
        if not group or group["disabled"] or group["is_group"]:
            throw("Select an active posting-level Supplier Group.")
        check_control_account(self.control_account, "Liability", "Payables", "Supplier Control Account")
        if self.advance_account:
            advance = row("Account", self.advance_account, "name", "root_type", "requires_party", "disabled")
            if not advance or advance["disabled"] or advance["root_type"] != "Asset" or not advance["requires_party"]:
                throw("Supplier Advance Account must be an active party-tracked Asset account.")
        if self.currency:
            self.currency = self.currency.strip().upper()
            if len(self.currency) != 3 or not self.currency.isalpha():
                throw("Supplier currency must be a three-letter ISO currency code.")
        if self.payment_terms:
            terms = row("Payment Terms", self.payment_terms, "name", "disabled")
            if not terms or terms["disabled"]:
                throw("Select active Payment Terms.")
        if self.supplier_type not in ("Company", "Individual"):
            throw("Select a valid Supplier Type.")

    def before_delete(self):
        ledger = get_table("Account Ledger Record")
        with db.transaction() as conn:
            used = conn.execute(select(ledger.c.name).where(ledger.c.party_type == "Supplier", ledger.c.party == self.name).limit(1)).first()
        if used:
            throw("This Supplier has financial ledger activity and cannot be deleted; disable it instead.")
