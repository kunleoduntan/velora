from decimal import Decimal

from velora import Document, new_doc, throw

from .... import common as c, ledger


class GeneralJournal(Document):
    def validate(self):
        jt, rows = self.journal_type, list(self.lines or [])
        if len(rows) < 2:
            throw("A journal needs at least two lines")
        infos = c.accounts_info([r.account for r in rows])
        td = tc = Decimal("0")
        for n, r in enumerate(rows, 1):
            dr, cr = c.money(r.debit or 0, f"Row {n} debit"), c.money(r.credit or 0, f"Row {n} credit")
            r.debit, r.credit = dr, cr
            if dr < 0 or cr < 0:
                throw(f"Row {n}: amounts cannot be negative")
            if dr and cr:
                throw(f"Row {n}: enter either a debit or a credit, not both")
            if not dr and not cr:
                throw(f"Row {n}: enter a debit or a credit amount")
            c.check_postable(infos.get(r.account), r.account, f"Row {n}")
            td, tc = td + dr, tc + cr
        if td != tc:
            throw(f"Debits ({td}) and credits ({tc}) must be equal; the difference is {td - tc}")
        self.total_debit, self.total_credit = td, tc
        ledger.validate_legs(self._legs())                 # the ledger's rules (incl. party rules) at SAVE time, not first at submit
        cash_rows = [(n, r) for n, r in enumerate(rows, 1) if c.is_cash(infos[r.account])]
        if jt == "Bank Transfer":
            if len({r.account for _, r in cash_rows}) < 2:
                throw("A Bank Transfer must move money between two different bank/cash accounts")
        elif jt != "Opening Balance" and cash_rows:
            n, r = cash_rows[0]
            throw(f"Row {n}: {r.account} is a bank/cash account. Money in or out of cash and bank is recorded with a Receipt or Payment "
                  "(or a Bank Transfer journal between your own accounts), so the cash book stays complete.")
        if jt == "Year-End Closing":
            for n, r in enumerate(rows, 1):
                i = infos[r.account]
                if i["root_type"] not in ("Income", "Expense") and i["account_type"] != "Retained Earnings":
                    throw(f"Row {n}: a Year-End Closing journal may only use Income, Expense and Retained Earnings accounts")
        if jt == "Reversing" and not self.is_auto_reversal:
            if not self.reverse_on:
                throw("A Reversing journal needs a 'Reverse On' date")
            if c.to_date(self.reverse_on, "Reverse on") <= c.to_date(self.posting_date, "Posting date"):
                throw("'Reverse On' must be after the posting date")
        elif self.reverse_on and jt != "Reversing":
            throw("'Reverse On' is only for Reversing journals")

    def _legs(self, mirror=False):
        out = []
        for r in self.lines:
            dr, cr = (r.credit, r.debit) if mirror else (r.debit, r.credit)
            out.append(ledger.Leg(r.account, dr, cr, r.party_type or None, r.party or None, r.narration or "", r.cost_center))
        return out

    def on_submit(self):
        ledger.post("General Journal", self.name, self.posting_date, self._legs(), self.remarks or self.reference or "")
        if self.journal_type == "Reversing" and self.reverse_on and not self.is_auto_reversal:
            ledger.check_open(self.reverse_on, "post a reversal dated")
            rev = new_doc("General Journal", journal_type="Reversing", posting_date=self.reverse_on, is_auto_reversal=1, reversal_of=self.name,
                          reference=self.reference, remarks=f"Auto-reversal of {self.name}", source_type=self.source_type, source_ref=self.source_ref)
            for r in self.lines:
                rev.append("lines", {"account": r.account, "party_type": r.party_type, "party": r.party, "debit": r.credit, "credit": r.debit,
                                     "narration": r.narration, "cost_center": r.cost_center})
            rev.insert(ignore_permissions=True).submit(ignore_permissions=True)

    def before_cancel(self):
        if self.is_auto_reversal and not getattr(self.flags, "cascade", False):
            throw(f"{self.name} is the automatic reversal of {self.reversal_of}. Cancel {self.reversal_of} instead.")

    def on_cancel(self):
        from velora import get_list, get_doc
        for r in get_list("General Journal", filters=[["reversal_of", "=", self.name], ["docstatus", "=", 1]], fields=["name"], ignore_permissions=True):
            d = get_doc("General Journal", r["name"], ignore_permissions=True)
            d.flags.cascade = True
            d.cancel(ignore_permissions=True)
        ledger.reverse("General Journal", self.name, self.remarks or "")
