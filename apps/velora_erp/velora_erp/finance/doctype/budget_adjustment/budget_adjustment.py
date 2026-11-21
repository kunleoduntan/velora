"""Budget Adjustment: an approved increase, decrease or transfer layered on an approved Financial Budget."""
from datetime import date
from decimal import Decimal, InvalidOperation
import calendar

from velora import Document, get_doc, throw
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition


class BudgetAdjustment(Document):
    def validate(self):
        validate_approval_transition(self)
        if not (self.reason or "").strip():
            throw("A reason is required for a budget adjustment.")
        budget = get_doc("Financial Budget", self.financial_budget, ignore_permissions=True)
        if budget.docstatus != 1 or budget.budget_status != "Active" or budget.approval_status != "Approved":
            throw("Adjustments can only be made to an active, approved and submitted budget.")
        if not self.lines:
            throw("At least one adjustment line is required.")
        year = get_doc("Financial Year", budget.financial_year, ignore_permissions=True)
        from velora_erp.finance.budget_control import _d
        net = positive = negative = Decimal("0")
        for i, line in enumerate(self.lines, 1):
            try:
                amount = _d(line.change_amount)
            except (InvalidOperation, ValueError):
                throw(f"Line {i}: Change must be a valid number.")
            if not amount.is_finite() or amount == 0:
                throw(f"Line {i}: Change must be a non-zero amount.")
            if not line.account or not line.period_start or not line.period_end:
                throw(f"Line {i}: Account, Period Start and Period End are required.")
            start, end = date.fromisoformat(str(line.period_start)[:10]), date.fromisoformat(str(line.period_end)[:10])
            if start.day != 1 or end != date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]):
                throw(f"Line {i}: each line must cover exactly one calendar month.")
            if start < year.start_date or end > year.end_date:
                throw(f"Line {i}: period must fall within Financial Year {budget.financial_year}.")
            if self.adjustment_type == "Increase" and amount < 0:
                throw(f"Line {i}: an Increase cannot contain negative changes.")
            if self.adjustment_type == "Decrease" and amount > 0:
                throw(f"Line {i}: a Decrease cannot contain positive changes.")
            net += amount
            positive += amount if amount > 0 else 0
            negative += amount if amount < 0 else 0
        if self.adjustment_type == "Transfer" and (net != 0 or not positive or not negative):
            throw("A Transfer must move budget from one allocation to another: its lines must include both a decrease and an increase and net to zero.")
        self.net_change = net

    def before_submit(self):
        ensure_approved(self, required=True)
        # No allocation may end up negative once this adjustment is applied.
        from velora_erp.finance.budget_control import effective_lines, _d, _date
        totals = {}
        for l in effective_lines(self.financial_budget):
            k = (l["account"], str(_date(l["period_start"])), l["cost_centre"] or "", l["branch"] or "", l["business_unit"] or "", l["project"] or "", l["department"] or "")
            totals[k] = totals.get(k, Decimal("0")) + l["amount"]
        for i, line in enumerate(self.lines, 1):
            k = (line.account, str(line.period_start)[:10], line.cost_centre or "", line.branch or "", line.business_unit or "", line.project or "", line.department or "")
            totals[k] = totals.get(k, Decimal("0")) + _d(line.change_amount)
            if totals[k] < 0:
                throw(f"Line {i}: the adjustment would take the budget for {line.account} {str(line.period_start)[:7]} below zero.")

    def on_submit(self):
        pass

def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted budget adjustment is retained for audit.")
