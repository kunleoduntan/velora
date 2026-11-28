"""Controlled employee separation and exit-clearance lifecycle."""
from datetime import date, datetime, timezone
from velora import Document, throw
from velora.permissions import get_session
from velora_erp.hr.common import decided_now


def _date(value):
    if not value:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _roles():
    session = get_session()
    return session, set(getattr(session, "roles", ()) or ())


class EmployeeSeparation(Document):
    def validate(self):
        notice = _date(self.notice_date)
        last_day = _date(self.last_working_date)
        if not notice or not last_day:
            throw("Notice Date and Last Working Date are required.")
        if last_day < notice:
            throw("Last Working Date cannot be earlier than Notice Date.")
        if not (self.reason or "").strip():
            throw("A documented reason is required for every separation.")

        if self.approval_status in {"Approved", "Rejected"} and decided_now(self, "approval_status"):
            session, _ = _roles()
            self.approved_by = session.user
            self.approved_on = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        items = list(getattr(self, "clearance_items", None) or [])
        seen_areas = set()
        for item in items:
            area = str(getattr(item, "clearance_area", "") or "").strip()
            status = getattr(item, "clearance_status", "Pending")
            if not area:
                throw("Every exit clearance item requires a Clearance Area.")
            if area.casefold() in seen_areas:
                throw("Each Clearance Area may appear only once in an exit checklist.")
            seen_areas.add(area.casefold())
            if status == "Cleared" and not getattr(item, "completed_on", None):
                item.completed_on = date.today()
        incomplete = [x for x in items if getattr(x, "clearance_status", "Pending") not in {"Cleared", "Not Applicable"}]
        self.clearance_completed = 1 if items and not incomplete else 0
        if self.workflow_status in {"Cleared", "Closed"} and not self.clearance_completed:
            throw("All exit clearance items must be Cleared or Not Applicable before the separation can be cleared.")
        if self.workflow_status == "Closed":
            if self.final_settlement_status != "Completed":
                throw("Finance final settlement must be marked Completed before closing the separation.")
            if not (self.finance_reference or "").strip():
                throw("A Finance settlement reference is required before closing the separation.")
            if decided_now(self, "workflow_status"):
                session, _ = _roles()
                self.closed_by = session.user
                self.closed_on = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        if self.final_settlement_status == "Completed" and not (self.finance_reference or "").strip():
            throw("Provide the Finance settlement reference when final settlement is completed.")

    def on_update(self):
        """Keep the Employee record in step: notice period once approved, Left (and inactive) once the separation is closed."""
        from velora import get_doc
        from velora_erp.finance.doctype._utils import db_update
        if self.workflow_status not in {"Approved", "Clearance In Progress", "Cleared", "Closed"} or not self.employee:
            return
        employee = get_doc("Employee", self.employee, ignore_permissions=True)
        if self.workflow_status == "Closed":
            values = {"employment_status": "Left", "relieving_date": _date(self.last_working_date), "disabled": 1}
            if not employee.resignation_date and self.notice_date:
                values["resignation_date"] = _date(self.notice_date)
        elif employee.employment_status in {"Active", "Probation", "On Leave"}:
            values = {"employment_status": "Notice Period"}
        else:
            return
        db_update(employee, **{k: v for k, v in values.items() if getattr(employee, k, None) != v})
