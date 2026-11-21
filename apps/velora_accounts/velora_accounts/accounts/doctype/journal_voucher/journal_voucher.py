from decimal import Decimal


from velora import Document, ValidationError, get_doc, new_doc, throw

from .... import common as c


class JournalVoucher(Document):
    """A batch: every line (or every group of lines sharing a Group reference) becomes its OWN General Journal.
    Submitting creates and submits them all in ONE transaction - if any line fails, none is created."""

    def _groups(self):
        groups: dict = {}
        for r in self.lines:
            groups.setdefault(r.group_ref or f"__row{r.idx}", []).append(r)
        return list(groups.values())

    def _journal(self, rows):
        first = rows[0]
        date = first.posting_date or self.voucher_date
        jtype = first.journal_type or self.default_journal_type
        for r in rows[1:]:
            if (r.posting_date or self.voucher_date) != date or (r.journal_type or self.default_journal_type) != jtype:
                throw(f"Lines {', '.join(str(x.idx) for x in rows)} share group {first.group_ref!r} but differ in date or journal type")
        gj = new_doc("General Journal", journal_type=jtype, posting_date=date, reference=self.title, source_type="Journal Voucher", source_ref=self.name,
                     remarks="; ".join(dict.fromkeys(r.narration for r in rows if r.narration))[:1000] or self.remarks)
        infos = c.accounts_info([a for r in rows for a in (r.debit_account, r.credit_account)])
        for r in rows:
            def party(acc, r=r):
                return (r.party_type or None, r.party or None) if infos.get(acc, {}).get("account_type") in c.PARTY_RULES else (None, None)
            gj.append("lines", {"account": r.debit_account, "debit": r.amount, "credit": 0, "narration": r.narration, "party_type": party(r.debit_account)[0], "party": party(r.debit_account)[1]})
            gj.append("lines", {"account": r.credit_account, "debit": 0, "credit": r.amount, "narration": r.narration, "party_type": party(r.credit_account)[0], "party": party(r.credit_account)[1]})
        for i, l in enumerate(gj.lines, 1):
            l.idx = i
        return gj

    def validate(self):
        if not self.lines:
            throw("Add at least one line")
        total = Decimal("0")
        for r in self.lines:
            r.amount = c.money(r.amount, f"Line {r.idx} amount")
            if r.amount <= 0:
                throw(f"Line {r.idx}: amount must be greater than zero")
            if r.debit_account == r.credit_account:
                throw(f"Line {r.idx}: the debit and credit accounts must differ")
            total += r.amount
        self.total_amount = total
        for rows in self._groups():                       # pre-flight: every rule of a General Journal, reported per line
            try:
                self._journal(rows).run_method("validate")
            except ValidationError as e:
                raise ValidationError(f"Line {rows[0].idx}: {e}") from None

    def before_submit(self):
        for rows in self._groups():
            gj = self._journal(rows)
            try:
                gj.insert(ignore_permissions=True).submit(ignore_permissions=True)    # the voucher's own submit permission is the gate
            except ValidationError as e:
                raise ValidationError(f"Line {rows[0].idx}: {e}") from None
            for r in rows:
                r.status, r.created_type, r.created_ref = "Created", "General Journal", gj.name

    def before_cancel(self):
        done = set()
        for r in self.lines:
            if r.created_ref and r.created_ref not in done:
                done.add(r.created_ref)
                get_doc("General Journal", r.created_ref, ignore_permissions=True).cancel(ignore_permissions=True)
            r.status = "Cancelled"
