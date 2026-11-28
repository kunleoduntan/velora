from datetime import datetime, timezone
from velora import Document, throw, get_list
from velora.permissions import get_session
from velora_erp.hr.common import decided_now
from velora_erp.hr import staffing


def _enforced():
    try:
        rows = get_list("Recruitment Settings", fields=["name", "require_department_staff_budget"], limit=1, ignore_permissions=True)
        return bool(rows and rows[0].get("require_department_staff_budget"))
    except Exception: return False


class JobRequisition(Document):
    def validate(self):
        if int(self.vacancy_count or 0) < 1: throw("Number of vacancies must be at least one.")
        if self.salary_minimum is not None and self.salary_maximum is not None and float(self.salary_maximum) < float(self.salary_minimum):
            throw("Salary range maximum cannot be below the minimum.")
        if self.requisition_status in {"Pending Approval", "Approved"}:
            self._check_staff_budget()
        if self.requisition_status in {"Approved", "Rejected"}:
            if decided_now(self,"requisition_status"):
                self.approved_by=get_session().user; self.approved_on=datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)

    def _check_staff_budget(self):
        """A request to employ must fit the department's approved staff budget (when the company enforces budgets)."""
        if not self.department or not self.designation: return
        budget, line = staffing.budget_for(self.department, self.designation, self.target_start_date)
        if budget is None:
            if _enforced():
                throw(f"There is no approved staff budget for {self.department} / {self.designation} on the target start date. Ask HR to approve a Department Staff Budget first.")
            return
        self.budget_reference = budget.name
        head = int(line.get("budgeted_headcount") if isinstance(line, dict) else line.budgeted_headcount or 0)
        room = head - staffing.filled(self.department, self.designation) - staffing.committed(
            self.department, self.designation, exclude=getattr(self, "name", None), start=budget.from_date, end=budget.to_date)
        if int(self.vacancy_count or 0) > room:
            throw(f"This request is for {int(self.vacancy_count)} position(s) but only {max(room, 0)} remain in the approved staff budget {budget.name} ({head} budgeted for {self.designation}).")
