from velora import Document, throw


class ApprovalEscalationRule(Document):
    def validate(self):
        if int(self.sla_hours or 0) <= 0:
            throw("SLA Hours must be greater than zero.")
        if self.scope == "Request" and not (self.escalate_to_user or self.escalate_to_role):
            throw("Request escalation requires an escalation user or role.")
        if self.escalate_to_user and self.escalate_to_role:
            throw("Configure either an escalation user or role, not both.")
