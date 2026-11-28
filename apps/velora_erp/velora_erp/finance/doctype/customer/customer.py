from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from velora import Document, throw, db
from velora.db.tables import get_table
from velora_erp.finance.validation import check_control_account, row


class Customer(Document):
    def validate(self):
        self.customer_code = (self.customer_code or "").strip().upper()
        self.customer_name = (self.customer_name or "").strip()
        if not self.customer_code or not self.customer_name:
            throw("Customer Code and Customer Name are required.")
        group = row("Customer Group", self.customer_group, "name", "disabled", "is_group")
        if not group or group["disabled"] or group["is_group"]:
            throw("Select an active posting-level Customer Group.")
        check_control_account(self.control_account, "Asset", "Receivables", "Customer Control Account")
        if self.advance_account:
            advance = row("Account", self.advance_account, "name", "root_type", "requires_party", "disabled")
            if not advance or advance["disabled"] or advance["root_type"] != "Liability" or not advance["requires_party"]:
                throw("Customer Advance Account must be an active party-tracked Liability account.")
        if self.currency:
            self.currency = self.currency.strip().upper()
            if len(self.currency) != 3 or not self.currency.isalpha():
                throw("Customer currency must be a three-letter ISO currency code.")
        if self.payment_terms:
            terms = row("Payment Terms", self.payment_terms, "name", "disabled")
            if not terms or terms["disabled"]:
                throw("Select active Payment Terms.")
        try:
            limit = Decimal(str(self.credit_limit or 0))
        except (InvalidOperation, ValueError):
            throw("Credit Limit must be a valid amount.")
        if not limit.is_finite() or limit < 0:
            throw("Credit Limit cannot be negative or non-finite.")
        if getattr(self, "credit_hold", 0) and not str(getattr(self, "credit_hold_reason", "") or "").strip():
            throw("Credit Hold Reason is required when a customer is placed on Credit Hold.")
        if self.customer_type not in ("Company", "Individual"):
            throw("Select a valid Customer Type.")

    def before_delete(self):
        ledger = get_table("Account Ledger Record")
        with db.transaction() as conn:
            used = conn.execute(select(ledger.c.name).where(ledger.c.party_type == "Customer", ledger.c.party == self.name).limit(1)).first()
        if used:
            throw("This Customer has financial ledger activity and cannot be deleted; disable it instead.")
