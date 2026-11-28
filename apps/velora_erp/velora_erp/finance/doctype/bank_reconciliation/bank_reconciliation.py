from decimal import Decimal
from velora import Document, throw, get_list
from velora_erp.finance import bank_reconciliation as svc

TOL = Decimal("0.005")
FIELDS = ["gl_account", "currency", "ledger_balance", "deposits_in_transit", "outstanding_payments", "adjusted_bank_balance", "unrecorded_receipts",
          "unrecorded_payments", "adjusted_book_balance", "variance", "statement_check", "statement_lines_total", "matched_lines", "suggested_lines", "unmatched_lines", "match_rate"]


class BankReconciliation(Document):
    def validate(self):
        if not self.bank_account or not self.to_date:
            return
        if self.from_date and str(self.from_date) > str(self.to_date):
            throw("From Date cannot be later than the reconciliation date.")
        prior = get_list("Bank Reconciliation", filters=[["bank_account", "=", self.bank_account], ["docstatus", "=", 1], ["to_date", ">=", str(self.to_date)]],
                         fields=["name", "to_date"], limit=5, ignore_permissions=True)
        prior = [p for p in prior if p["name"] != self.name]
        if prior:
            throw(f"{prior[0]['name']} already reconciles this account up to {prior[0]['to_date']}. Choose a later date, or cancel that reconciliation first.")
        res = svc.compute(self.bank_account, self.from_date, self.to_date, self.statement_opening_balance if self.statement_opening_balance not in (None, "") else None, self.statement_closing_balance)
        for f in FIELDS:
            setattr(self, f, res[f])
        self.status = "Reconciled" if abs(Decimal(str(res["variance"]))) <= TOL else "Unbalanced"
        self.items = []
        for it in res["items"]:
            self.append("items", it)
        self._link_children()
        self._cleared_groups = res["cleared_group_ids"]

    def before_submit(self):
        if self.status != "Reconciled":
            throw(f"The reconciliation is not balanced: the variance is {self.variance:,.2f}. Match or post the remaining items first.")
        if self.statement_check and abs(Decimal(str(self.statement_check))) > TOL:
            throw(f"The statement does not add up: opening balance plus its lines differs from the closing balance by {self.statement_check:,.2f}. Import the missing lines or correct the balances.")

    def on_submit(self):
        svc.lock(self.name, self.bank_account, getattr(self, "_cleared_groups", []), True)

    def on_cancel(self):
        groups = {m["match_group"] for m in get_list("Bank Reconciliation Match", filters=[["reconciliation", "=", self.name]], fields=["match_group"], limit=100000, ignore_permissions=True)}
        svc.lock(self.name, self.bank_account, sorted(groups), False)
        self.status = "Draft"
