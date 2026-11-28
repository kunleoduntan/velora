from decimal import Decimal

from velora import Document, throw

from .... import common as c, ledger, settlement
from ..receipt.receipt import gateway_duplicate, settle_amounts


class Payment(Document):
    def validate(self):
        kind = self.payment_type
        lines = list(self.lines or [])
        infos = settle_amounts(self, None, "payment")
        if kind == "Vendor":
            if lines:
                throw("A Vendor payment is applied to the payee's account: remove the lines, or use payment type Other")
            if not self.party:
                throw("Choose who is being paid")
            c.require_parties([(self.party_type or "Supplier", self.party)])
            total = c.money(self.amount, "Amount")
        else:
            if self.invoices:
                throw("Invoices can only be settled by a Vendor payment")
            if not lines:
                throw("Add at least one line saying what this payment is for")
            total = Decimal("0")
            for n, r in enumerate(lines, 1):
                r.amount = c.money(r.amount, f"Row {n} amount")
                if r.amount <= 0:
                    throw(f"Row {n}: amount must be greater than zero")
                c.check_postable(infos.get(r.account), r.account, f"Row {n}")
                if c.is_cash(infos[r.account]):
                    throw(f"Row {n}: {r.account} is a bank/cash account. To move money between your own accounts use a Bank Transfer journal")
                total += r.amount
            self.amount = total
        if total <= 0:
            throw("The payment amount must be greater than zero")
        wht = c.round_money(total * c.D(self.wht_rate) / 100) if c.D(self.wht_rate) > 0 else c.money(self.wht_amount or 0, "WHT")
        if wht < 0:
            throw("WHT cannot be negative")
        if wht:
            self.wht_account = self.wht_account or c.get_default("wht_payable")
            if c.accounts_info([self.wht_account]).get(self.wht_account, {}).get("account_type") != "Tax":
                throw(f"{self.wht_account} is not a Tax account")
        self.wht_amount, self.total = wht, total
        if kind == "Vendor" and self.invoices and (self.party_type or "Supplier") != "Supplier":
            throw("Invoices can only be settled for a Supplier")
        alloc, disc = settlement.prepare(self, "Purchase Invoice", "supplier", total) if kind == "Vendor" else (Decimal("0"), Decimal("0"))
        self.allocated_total, self.discount_total, self.on_account = alloc, disc, total - alloc
        if disc:
            c.check_postable(c.accounts_info([c.get_default("discount_received")]).get(c.get_default("discount_received")), "Discount Received", "Discount account")
        self.bank_amount = total - wht
        if self.bank_amount <= 0:
            throw("WHT leaves nothing to pay from the bank")
        gateway_duplicate(self, "Payment")

    def _legs(self):
        if self.payment_type == "Vendor":
            legs = [ledger.Leg(c.get_default("payable"), debit=self.total + (self.discount_total or 0), party_type=self.party_type or "Supplier", party=self.party, remarks=self.reference_no or "")]
            if self.discount_total:
                legs.append(ledger.Leg(c.get_default("discount_received"), credit=self.discount_total, remarks="Settlement discount received"))
        else:
            legs = [ledger.Leg(r.account, debit=r.amount, party_type=r.party_type or None, party=r.party or None, remarks=r.narration or "") for r in self.lines]
        legs.append(ledger.Leg(self.bank_account, credit=self.bank_amount, remarks=self.reference_no or ""))
        if self.wht_amount:
            legs.append(ledger.Leg(self.wht_account, credit=self.wht_amount, remarks="Withholding tax deducted"))
        return legs

    def on_submit(self):
        settlement.apply(self, "Purchase Invoice", +1)
        ledger.post("Payment", self.name, self.posting_date, self._legs(), self.remarks or "")

    def on_cancel(self):
        ledger.reverse("Payment", self.name, self.remarks or "")
        settlement.apply(self, "Purchase Invoice", -1)
