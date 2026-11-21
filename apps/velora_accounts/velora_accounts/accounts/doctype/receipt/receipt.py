from decimal import Decimal

from velora import Document, get_list, throw

from .... import common as c, ledger, settlement


def gateway_duplicate(doc, doctype):
    if doc.gateway_reference:
        if not doc.gateway:
            throw("Name the gateway for this gateway reference")
        flt = [["gateway", "=", doc.gateway], ["gateway_reference", "=", doc.gateway_reference], ["docstatus", "<", 2]]
        if doc.name:
            flt.append(["name", "!=", doc.name])
        dup = get_list(doctype, filters=flt, fields=["name"], limit=1, ignore_permissions=True)
        if dup:
            throw(f"{doc.gateway} reference {doc.gateway_reference} is already recorded on {dup[0]['name']}")


def settle_amounts(doc, lines_ok_accounts, what):
    """Shared by Receipt and Payment: totals, WHT and the cash/bank account. Returns (total, wht, infos)."""
    infos = c.accounts_info([doc.bank_account] + [r.account for r in doc.lines] + [doc.wht_account, getattr(doc, "fee_account", None)])
    cash = c.check_postable(infos.get(doc.bank_account), doc.bank_account, "Cash / Bank Account")
    if not c.is_cash(cash):
        throw(f"{doc.bank_account} is not a Bank or Cash account")
    return infos


class Receipt(Document):
    def validate(self):
        kind = self.receipt_type
        lines = list(self.lines or [])
        infos = settle_amounts(self, None, "receipt")
        if kind == "Customer":
            if lines:
                throw("A Customer receipt is applied to the customer's account: remove the lines, or use receipt type Other")
            if not self.party:
                throw("Choose the customer this receipt is from")
            c.require_parties([("Customer", self.party)])
            total = c.money(self.amount, "Amount")
        else:
            if self.invoices:
                throw("Invoices can only be settled by a Customer receipt")
            if not lines:
                throw("Add at least one line saying what this money is for")
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
            throw("The receipt amount must be greater than zero")
        wht = c.round_money(total * c.D(self.wht_rate) / 100) if c.D(self.wht_rate) > 0 else c.money(self.wht_amount or 0, "WHT")
        fee = c.money(self.fee_amount or 0, "Fee")
        if wht < 0 or fee < 0:
            throw("WHT and fees cannot be negative")
        if wht:
            self.wht_account = self.wht_account or c.get_default("wht_receivable")
            if c.accounts_info([self.wht_account]).get(self.wht_account, {}).get("account_type") != "Tax":
                throw(f"{self.wht_account} is not a Tax account")
        if fee:
            self.fee_account = self.fee_account or c.get_default("gateway_fees")
            c.check_postable(c.accounts_info([self.fee_account]).get(self.fee_account), self.fee_account, "Fee account")
        self.wht_amount, self.fee_amount, self.total = wht, fee, total
        alloc, disc = settlement.prepare(self, "Sales Invoice", "customer", total) if kind == "Customer" else (Decimal("0"), Decimal("0"))
        self.allocated_total, self.discount_total, self.on_account = alloc, disc, total - alloc
        if disc:
            c.check_postable(c.accounts_info([c.get_default("discount_allowed")]).get(c.get_default("discount_allowed")), "Discount Allowed", "Discount account")
        self.bank_amount = total - wht - fee
        if self.bank_amount <= 0:
            throw("WHT and fees leave nothing received in the bank")
        gateway_duplicate(self, "Receipt")

    def _legs(self):
        legs = [ledger.Leg(self.bank_account, debit=self.bank_amount, remarks=self.reference_no or "")]
        if self.wht_amount:
            legs.append(ledger.Leg(self.wht_account, debit=self.wht_amount, remarks="Withholding tax suffered"))
        if self.fee_amount:
            legs.append(ledger.Leg(self.fee_account, debit=self.fee_amount, remarks="Gateway / bank fee"))
        if self.receipt_type == "Customer":
            if self.discount_total:
                legs.append(ledger.Leg(c.get_default("discount_allowed"), debit=self.discount_total, remarks="Settlement discount allowed"))
            legs.append(ledger.Leg(c.get_default("receivable"), credit=self.total + (self.discount_total or 0), party_type="Customer", party=self.party, remarks=self.reference_no or ""))
        else:
            legs += [ledger.Leg(r.account, credit=r.amount, party_type=r.party_type or None, party=r.party or None, remarks=r.narration or "") for r in self.lines]
        return legs

    def on_submit(self):
        settlement.apply(self, "Sales Invoice", +1)          # first: a stale invoice fails here, with a clear message
        ledger.post("Receipt", self.name, self.posting_date, self._legs(), self.remarks or "")

    def on_cancel(self):
        ledger.reverse("Receipt", self.name, self.remarks or "")
        settlement.apply(self, "Sales Invoice", -1)
