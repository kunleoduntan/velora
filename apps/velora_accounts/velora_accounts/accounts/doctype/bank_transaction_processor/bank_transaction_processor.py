from decimal import Decimal

from velora import throw

from ....batch import BatchDocument
from .... import common as c


class BankTransactionProcessor(BatchDocument):
    """One bank statement period. Rows must fall inside the period, and (given opening and closing balances) must add up to the statement."""
    BANK_FIELD = "bank_account"
    DATE_FIELD = None

    def default_method(self):
        return "Bank Transfer"

    def check_row_date(self, row, d):
        if not d:
            throw("enter the transaction date")
        a, b = c.to_date(self.statement_from, "Statement from"), c.to_date(self.statement_to, "Statement to")
        if b < a:
            throw("'Statement To' is before 'Statement From'")
        if not a <= c.to_date(d) <= b:
            throw(f"{c.to_date(d).isoformat()} is outside the statement period {a.isoformat()} to {b.isoformat()}")

    def check_total(self, bank_effect: Decimal):
        o, cl = self.opening_balance, self.closing_balance
        if o is None or cl is None:
            self.statement_note = "Opening/closing balance not entered: statement not proved"
            return
        o, cl = c.money(o, "Opening balance"), c.money(cl, "Closing balance")
        expected = o + bank_effect
        f = lambda x: f"{x:,.2f}"
        if expected != cl:
            throw(f"The rows do not add up to the statement: opening {f(o)} + movements {f(bank_effect)} = {f(expected)}, but the closing balance is {f(cl)} "
                  f"(difference {f(cl - expected)}). A row is missing, duplicated or mistyped.")
        self.statement_note = f"Proved: opening {f(o)} + movements {f(bank_effect)} = closing {f(cl)}"
