from datetime import date

from velora import Document, get_list, throw
from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition
from velora_erp.finance.validation import row
from velora_erp.treasury import service as svc
from velora_erp.treasury.engine import BASES, STRUCTURES

KINDS = {"loan_liability_account": ("Liability", "loan liability"), "interest_expense_account": ("Expense", "interest expense"),
         "accrued_interest_account": ("Liability", "accrued interest"), "fee_expense_account": ("Expense", "fees")}
REVOLVING = ("Revolving Credit", "Overdraft")


class FinancingFacility(Document):
    def validate(self):
        lender = row("Financial Institution", self.financial_institution, "name", "disabled")
        if not lender or lender["disabled"]:
            throw("Choose an active lender.")
        self.currency = (self.currency or svc.base_currency()).upper()
        if float(self.approved_limit or 0) <= 0:
            throw("The approved limit must be greater than zero.")
        if not self.start_date or not self.expiry_date or self.expiry_date < self.start_date:
            throw("The availability end date cannot be before the start date.")
        if float(self.interest_rate or 0) < 0:
            throw("The interest rate cannot be negative.")
        if self.interest_rate_type == "Floating" and (self.rate_spread or self.reference_rate_name):
            pass
        if self.repayment_structure not in STRUCTURES or self.day_count_basis not in BASES:
            throw("Choose a valid repayment structure and day count.")
        if self.facility_type in REVOLVING:
            self.allows_redraw = 1
        if not self.fee_expense_account:
            self.fee_expense_account = self.interest_expense_account
        for field, (root, label) in KINDS.items():
            code = getattr(self, field)
            a = row("Account", code, "name", "disabled", "is_group", "root_type") if code else None
            if not a or a["disabled"] or a["is_group"] or a["root_type"] != root:
                throw(f"The {label} account must be an active posting account of type {root.lower()}.")
        if self.wht_rule:
            self.wht_rule = self.wht_rule.strip().upper()
            if not get_list("Tax Rule", filters=[["rule_code", "=", self.wht_rule], ["tax_type", "=", "WHT"], ["docstatus", "=", 1]], fields=["name"], limit=1, ignore_permissions=True):
                throw(f"{self.wht_rule} is not an approved withholding tax rule.")
        names = [c.covenant_name.strip().lower() for c in self.covenants or []]
        if len(names) != len(set(names)):
            throw("Two covenants have the same name.")
        for c in self.covenants or []:
            if c.operator not in ("<=", "<", ">=", ">"):
                throw(f"Covenant {c.covenant_name}: choose how the value is compared with the limit.")
        validate_approval_transition(self)

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        from velora_erp.finance.doctype._utils import db_update
        db_update(self, status="Active" if self.expiry_date >= date.today() else "Expired", outstanding_principal=0, total_drawn=0, undrawn_available=self.approved_limit, utilisation_percent=0)

    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted facility cannot be deleted; cancel it instead.")
