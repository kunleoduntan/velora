"""Validation and confidentiality controls for employee relations cases."""
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


class EmployeeRelationsCase(Document):
    def validate(self):
        session, roles = _roles()
        privileged = session.user == "Administrator" or bool(roles.intersection({"System Manager", "HR Manager"}))
        if not privileged:
            throw("Employee relations cases are restricted to HR Managers and System Managers.")
        reported = _date(self.reported_date)
        incident = _date(self.incident_date)
        target = _date(self.target_resolution_date)
        if not reported:
            throw("Reported Date is required.")
        if incident and incident > reported:
            throw("Incident Date cannot be later than Reported Date.")
        if target and target < reported:
            throw("Target Resolution Date cannot be earlier than Reported Date.")
        if self.case_status in {"Resolved", "Closed"}:
            if not (self.resolution_summary or "").strip():
                throw("A resolution summary is required before resolving or closing a case.")
            if not self.outcome:
                throw("Select an outcome before resolving or closing a case.")
            if decided_now(self, "case_status"):
                self.closed_by = session.user
                self.closed_on = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        if self.case_status == "Under Investigation" and not (self.assigned_investigator or "").strip():
            throw("Assign an investigator before moving the case to Under Investigation.")
        for action in (getattr(self, "actions", None) or []):
            action_date = _date(getattr(action, "action_date", None))
            action_type = getattr(action, "action_type", None)
            if not action_date or not action_type:
                throw("Every case action requires an Action Date and Action Type.")
            if action_date < reported:
                throw("Case action dates cannot precede the case Reported Date.")
            if action_type == "Decision" and not (getattr(action, "notes", "") or "").strip():
                throw("A Decision action requires documented decision notes.")
            if action_type == "Evidence Review" and not (getattr(action, "evidence_reference", "") or "").strip():
                throw("An Evidence Review action requires an Evidence Reference.")
