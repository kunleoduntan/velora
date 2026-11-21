"""Employee self-service request ownership and HR resolution controls."""
from datetime import datetime
from velora import Document, throw, get_doc, get_list
from velora.permissions import get_session


_HR_ROLES = {"System Manager", "HR Manager", "HR Officer"}


class HRServiceRequest(Document):
    def validate(self):
        session = get_session()
        roles = set(getattr(session, "roles", ()) or ())
        is_hr = session.user == "Administrator" or bool(roles.intersection(_HR_ROLES))
        if not self.employee:
            throw("Employee is required.")
        if not (self.subject or "").strip() or not (self.details or "").strip():
            throw("Request Subject and Details are required.")

        # Employee-role users may only create or maintain requests for the
        # canonical Employee record linked to their authenticated account.
        if not is_hr:
            employee = get_doc("Employee", self.employee, ignore_permissions=True)
            if employee.disabled or (employee.user_account or "").casefold() != str(session.user or "").casefold():
                throw("You may only access HR service requests linked to your own active Employee account.")
            if self.request_status not in {"Open", "Waiting for Employee"}:
                throw("Employees cannot assign, resolve, close or reject their own HR service requests.")
            if self.assigned_to or self.resolution or self.resolved_on:
                throw("Employees cannot modify HR assignment or resolution fields.")
        else:
            if self.request_status in {"Resolved", "Closed", "Rejected"}:
                if session.user != "Administrator" and not roles.intersection(_HR_ROLES):
                    throw("Only HR service staff may resolve or close requests.")
                if self.request_status == "Resolved" and not (self.resolution or "").strip():
                    throw("A resolution note is required before resolving a request.")
                if self.request_status == "Resolved":
                    self.resolved_on = datetime.utcnow().replace(microsecond=0)
