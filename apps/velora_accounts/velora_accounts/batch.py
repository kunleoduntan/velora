"""The batch engine behind Batch Bank Transaction, Expense Batch and Bank Transaction Processor.

Every row of a batch becomes ONE Receipt, Payment or Bank Transfer journal - the router decides, nobody picks a document type:

    money in  (inflow)   -> Receipt   (a Customer receipt when a customer is named without an account, else an Other receipt)
    money out (outflow)  -> Payment   (a Vendor payment when a supplier/employee is named without an account, else an Other payment)
    Transfer             -> General Journal of type Bank Transfer (between two of your own bank/cash accounts)

Guarantees (each one learned the hard way in Ecclesia):
  * PRE-FLIGHT: on save, every row is built as the real voucher and validated; ALL problems are reported together, per row.
  * ALL-OR-NOTHING: submitting creates every voucher in one transaction; if one row fails, nothing is created.
  * TRACEABLE: each row records what it created, so cancelling a batch is exact and nothing can be created twice.
  * DUPLICATES: a row whose bank, date, amount and reference match an existing Receipt/Payment is refused (re-importing a statement is safe).
  * Draft vs submitted vouchers is the batch's own, immutable choice (a submitted batch can't change it).
"""
from __future__ import annotations

import re
from decimal import Decimal

from velora import Document, ValidationError, get_doc, get_list, new_doc, throw
from velora.exceptions import DoesNotExistError, VeloraError

from . import amortisation, common as c, ledger

MAX_REPORTED = 25
_INNER_ROW = re.compile(r"^Row \d+: ")


def _clean(e) -> str:
    """The generated voucher numbers ITS lines; the person only knows the batch row, so drop the voucher's own 'Row n:' prefix."""
    return _INNER_ROW.sub("", str(e))


FIELDS = ("posting_date", "trans_type", "bank_account", "inflow", "outflow", "account", "party_type", "party", "narration", "reference_no",
          "method", "wht_rate", "fee_amount", "amortise", "spread_periods", "expense_account", "amortise_from", "allow_duplicate")


class BatchDocument(Document):
    BANK_FIELD = "bank_account"        # the parent field holding the batch's default bank/cash account
    DATE_FIELD: str | None = "batch_date"

    # ---- hooks a concrete batch can refine --------------------------------------------------------------------
    def default_bank(self):
        return self.get(self.BANK_FIELD)

    def default_date(self):
        return self.get(self.DATE_FIELD) if self.DATE_FIELD else None

    def default_method(self):
        return self.get("method") or "Bank Transfer"

    def skip_row(self, row, direction: str) -> bool:
        return False

    def check_total(self, bank_effect: Decimal) -> None:
        """Whole-batch check once every row is known (the Processor proves the rows add up to the statement)."""

    def check_row_date(self, row, d) -> None:
        """The Processor keeps every row inside the statement period."""

    # ---- one row -----------------------------------------------------------------------------------------------
    def _direction(self, row) -> tuple[str, Decimal]:
        i, o = c.money(row.inflow or 0, "Money In"), c.money(row.outflow or 0, "Money Out")
        if i < 0 or o < 0:
            throw("amounts cannot be negative; use Money In or Money Out")
        if i and o:
            throw("enter Money In or Money Out, not both")
        if not i and not o:
            throw("enter an amount in Money In or Money Out")
        return ("in", i) if i else ("out", o)

    def _type(self, row, direction: str) -> str:
        t = row.trans_type or ("Receipt" if direction == "in" else "Payment")
        if t == "Receipt" and direction != "in":
            throw("a Receipt row needs Money In")
        if t == "Payment" and direction != "out":
            throw("a Payment row needs Money Out")
        return t

    def _amortise(self, row, direction: str) -> tuple[str, str, int]:
        if direction != "out" or self._type(row, direction) != "Payment":
            throw("only Payment rows (money out) can be amortised")
        n = int(row.spread_periods or 0)
        if not 2 <= n <= 60:
            throw("'Spread Over (months)' must be between 2 and 60")
        if not row.expense_account:
            throw("name the Expense Account that each month's share is charged to")
        if row.party or row.party_type:
            throw("an amortised row cannot carry a party")
        prepaid = row.account or c.get_default("prepayments")
        info = c.accounts_info([prepaid, row.expense_account])
        c.check_postable(info.get(prepaid), prepaid, "Prepaid account")
        e = c.check_postable(info.get(row.expense_account), row.expense_account, "Expense account")
        if e["root_type"] != "Expense":
            throw(f"{row.expense_account} is not an Expense account")
        if c.is_cash(info[prepaid]):
            throw(f"{prepaid} is a bank/cash account and cannot hold prepayments")
        return prepaid, row.expense_account, n

    def make_voucher(self, row, direction: str, amount: Decimal):
        """Build (not save) the Receipt / Payment / Bank Transfer this row stands for."""
        bank = row.bank_account or self.default_bank()
        if not bank:
            throw("name a bank/cash account (on the row, or on the batch)")
        date = row.posting_date or self.default_date()
        if not date:
            throw("enter a date")
        kind = self._type(row, direction)
        common = dict(posting_date=date, bank_account=bank, reference_no=row.reference_no, remarks=row.narration, source_type=self.doctype, source_ref=self.name)
        method = row.method or self.default_method()
        party_line = {"party_type": row.party_type or None, "party": row.party or None}
        if kind == "Transfer":
            if not row.account:
                throw("name the other bank/cash account in 'Account'")
            gj = new_doc("General Journal", journal_type="Bank Transfer", posting_date=date, reference=row.reference_no, remarks=row.narration,
                         source_type=self.doctype, source_ref=self.name)
            to, frm = (bank, row.account) if direction == "in" else (row.account, bank)
            gj.append("lines", {"account": to, "debit": amount, "credit": 0, "narration": row.narration})
            gj.append("lines", {"account": frm, "debit": 0, "credit": amount, "narration": row.narration})
            return gj
        if kind == "Receipt":
            customer = row.party_type == "Customer" and row.party and not row.account
            doc = new_doc("Receipt", receipt_type="Customer" if customer else "Other", method=method, wht_rate=row.wht_rate or 0, fee_amount=row.fee_amount or 0, **common)
            if customer:
                doc.party, doc.amount = row.party, amount
            else:
                if not row.account:
                    throw("name the Account this money is for (or a Customer to settle)")
                doc.append("lines", {"account": row.account, "amount": amount, "narration": row.narration, **party_line})
            return doc
        # Payment
        if row.fee_amount:
            throw("fees apply to receipts only; record bank charges as their own row")
        if row.amortise:
            prepaid, _, _ = self._amortise(row, direction)
            doc = new_doc("Payment", payment_type="Other", method=method, wht_rate=row.wht_rate or 0, **common)
            doc.append("lines", {"account": prepaid, "amount": amount, "narration": row.narration})
            return doc
        vendor = row.party and row.party_type in ("Supplier", "Employee") and not row.account
        doc = new_doc("Payment", payment_type="Vendor" if vendor else "Other", method=method, wht_rate=row.wht_rate or 0, **common)
        if vendor:
            doc.party_type, doc.party, doc.amount = row.party_type, row.party, amount
        else:
            if not row.account:
                throw("name the Account this money is for (or a Supplier / Employee to pay)")
            doc.append("lines", {"account": row.account, "amount": amount, "narration": row.narration, **party_line})
        return doc

    @staticmethod
    def bank_effect(doc, direction: str, amount: Decimal) -> Decimal:
        """What this voucher does to the bank balance (positive = money in)."""
        if doc.doctype == "Receipt":
            return doc.bank_amount
        if doc.doctype == "Payment":
            return -doc.bank_amount
        return amount if direction == "in" else -amount

    def _duplicate(self, doc, row, seen: set) -> None:
        if row.allow_duplicate or not row.reference_no or doc.doctype == "General Journal":
            return
        key = (doc.doctype, doc.bank_account, str(doc.posting_date)[:10], doc.reference_no, doc.total)
        if key in seen:
            throw(f"duplicate of an earlier row in this batch (same bank, date, reference {row.reference_no!r} and amount). Tick 'Allow Duplicate' if it is genuine")
        seen.add(key)
        flt = [["bank_account", "=", doc.bank_account], ["posting_date", "=", c.to_date(doc.posting_date)], ["reference_no", "=", doc.reference_no],
               ["total", "=", doc.total], ["docstatus", "<", 2]]
        if self.name:
            flt.append(["source_ref", "!=", self.name])
        hit = get_list(doc.doctype, filters=flt, fields=["name"], limit=1, ignore_permissions=True)
        if hit:
            throw(f"{doc.doctype} {hit[0]['name']} already records this (same bank, date, reference {row.reference_no!r} and amount). "
                  "Tick 'Allow Duplicate' if it is genuine")

    # ---- save: pre-flight the whole batch ----------------------------------------------------------------------
    def validate(self):
        if not self.lines:
            throw("Add at least one transaction")
        errors, seen = [], set()
        effect = tin = tout = Decimal("0")
        for row in self.lines:
            if row.created_ref:
                continue
            row.status = "Pending"
            try:
                direction, amount = self._direction(row)
                if self.skip_row(row, direction):
                    row.status = "Skipped"
                    continue
                self.check_row_date(row, row.posting_date or self.default_date())
                doc = self.make_voucher(row, direction, amount)
                doc.run_method("validate")                      # every rule of the real voucher, now - not first at submit
                if row.amortise:
                    self._amortise(row, direction)
                self._duplicate(doc, row, seen)
                if self.create_as == "Submitted":
                    ledger.check_open(doc.posting_date)
                effect += self.bank_effect(doc, direction, amount)
                tin, tout = (tin + amount, tout) if direction == "in" else (tin, tout + amount)
            except (VeloraError, ValueError) as e:
                errors.append(f"Row {row.idx}: {_clean(e)}")
        if errors:
            more = f"\n... and {len(errors) - MAX_REPORTED} more row(s) with problems" if len(errors) > MAX_REPORTED else ""
            raise ValidationError("\n".join(errors[:MAX_REPORTED]) + more)
        self.total_inflow, self.total_outflow = tin, tout
        self.check_total(effect)

    # ---- submit: create everything or nothing ------------------------------------------------------------------
    def before_submit(self):
        created = 0
        for row in self.lines:
            if row.status == "Skipped" or row.created_ref:
                continue
            direction, amount = self._direction(row)
            doc = self.make_voucher(row, direction, amount)
            try:
                doc.insert(ignore_permissions=True)           # the batch's own submit permission is the gate
                if self.create_as == "Submitted":
                    doc.submit(ignore_permissions=True)
                if row.amortise:
                    prepaid, expense, n = self._amortise(row, direction)
                    amortisation.schedule(voucher_type=doc.doctype, voucher_no=doc.name, source_type=self.doctype, source_ref=self.name, line_no=row.idx,
                                          amount=amount, start=row.amortise_from or doc.posting_date, periods=n, expense_account=expense, prepaid_account=prepaid)
            except VeloraError as e:
                raise ValidationError(f"Row {row.idx}: {_clean(e)}") from None
            row.status, row.created_type, row.created_ref = "Created", doc.doctype, doc.name
            created += 1
        if not created:
            throw("Nothing to create: every row is skipped")

    def before_cancel(self):
        amortisation.cancel_for(self.doctype, self.name)       # posted months first (their period must be open), then the payments
        for row in reversed(list(self.lines)):
            if row.created_ref:
                try:
                    v = get_doc(row.created_type, row.created_ref, ignore_permissions=True)
                except DoesNotExistError:
                    v = None
                if v is not None and v.docstatus == 1:
                    v.cancel(ignore_permissions=True)
                elif v is not None and v.docstatus == 0:
                    v.delete(ignore_permissions=True)          # a draft that never posted: remove it
            if row.status != "Skipped":
                row.status = "Cancelled"
