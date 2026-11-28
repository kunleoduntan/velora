"""Validation for effective-dated employee reporting assignments."""
from datetime import date
from velora import Document, get_list, throw
from velora.permissions import get_session


def _as_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class ReportingAssignment(Document):
    def validate(self):
        start = _as_date(self.effective_from)
        end = _as_date(self.effective_to)
        if not start:
            throw("Effective From is required.")
        if end and end < start:
            throw("Effective To cannot be earlier than Effective From.")
        if not self.employee or not self.department:
            throw("Employee and Department are required.")
        if self.assignment_status == "Approved":
            session = get_session()
        if self.assignment_status != "Approved" or not self.is_primary:
            return
        rows = get_list(
            "Reporting Assignment",
            filters={"employee": self.employee, "assignment_status": "Approved", "is_primary": 1},
            fields=["name", "effective_from", "effective_to"],
            limit=1000,
            ignore_permissions=True,
        )
        for row in rows:
            if row["name"] == getattr(self, "name", None):
                continue
            other_start = _as_date(row.get("effective_from"))
            other_end = _as_date(row.get("effective_to"))
            if not other_start:
                continue
            if (end is None or other_start <= end) and (other_end is None or other_end >= start):
                throw(
                    "This employee already has an approved primary reporting assignment "
                    f"({row['name']}) that overlaps the selected effective dates."
                )

    def on_update(self):
        """The approved primary assignment in force is the employee's reporting line: keep Employee.reports_to in step with it."""
        if self.assignment_status != "Approved" or not self.is_primary or not self.employee or not self.reports_to:
            return
        start, end = _as_date(self.effective_from), _as_date(self.effective_to)
        today = date.today()
        if start and start > today or end and end < today:
            return
        from velora import get_doc
        from velora_erp.finance.doctype._utils import db_update
        emp = get_doc("Employee", self.employee, ignore_permissions=True)
        if emp.get("reports_to") != self.reports_to:
            db_update(emp, reports_to=self.reports_to)
