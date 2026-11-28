from datetime import date

from velora import Document, throw


class ApprovalDelegation(Document):
    """Validate delegation dates, identity and scope."""

    def validate(self):
        delegator = str(self.delegator_user or "").strip()
        delegate = str(self.delegate_user or "").strip()
        if not delegator or not delegate:
            throw("Delegator and Delegate are required.")
        if delegator == delegate:
            throw("A user cannot delegate approval authority to themselves.")
        if not self.start_date or not self.end_date:
            throw("Delegation start and end dates are required.")
        if str(self.end_date) < str(self.start_date):
            throw("Delegation end date cannot be before its start date.")
        if self.status == "Active":
            today = date.today().isoformat()
            if str(self.start_date) > today or str(self.end_date) < today:
                throw("An Active delegation must be within its effective date range.")
        scope = str(self.doctype_scope or "Request").strip()
        if scope not in ("Request", "*"):
            throw("Delegation scope must be Request or *.")
        self.doctype_scope = scope
