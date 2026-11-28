from velora import Document, get_doc, get_list, new_doc, throw

class ComplianceAssessment(Document):
    def validate(self):
        obligations = get_list("Governance Obligation", filters=[["name", "=", self.obligation]], fields=["governance_entity", "responsible_owner", "due_date", "requirement"], limit=1)
        if not obligations:
            throw("The selected Governance Obligation could not be found.")
        obligation = obligations[0]
        if self.governance_entity and self.governance_entity != obligation.get("governance_entity"):
            throw("Assessment Governance Entity must match the Obligation.")
        self.governance_entity=obligation.get("governance_entity")
        if self.assessment_status == "Completed" and (not self.assessment_date or not self.assessor):
            throw("Completed Compliance Assessments require an Assessment Date and Assessor.")
        if self.assessment_status == "Completed" and self.assessment_result == "Non-Compliant" and not self.remediation_due_date:
            throw("Non-Compliant assessments require a Remediation Due Date.")

    def after_insert(self):
        self._complete_obligation_and_action()

    def on_update(self):
        self._complete_obligation_and_action()

    def _complete_obligation_and_action(self):
        if self.assessment_status != "Completed":
            return
        obligation = get_doc("Governance Obligation", self.obligation, ignore_permissions=True)
        if self.assessment_result == "Non-Compliant" and not self.remediation_action:
            types = get_list("Board Action Type", fields=["name", "action_type_name"], limit=1000, ignore_permissions=True)
            action_type = next((r["name"] for r in types if r.get("action_type_name") == "Compliance Action"), types[0]["name"] if types else None)
            action = new_doc("Board Action", action_title=f"Remediate compliance finding: {self.name}", governance_entity=self.governance_entity, action_type=action_type, assigned_owner=obligation.responsible_owner or self.assessor, due_date=self.remediation_due_date or obligation.due_date, priority="High", action_status="Open", progress_percent=0, notes=self.findings)
            action.insert(ignore_permissions=True)
            self.remediation_action=action.name
            self.save(ignore_permissions=True)
            return  # on_update performed the obligation sync; avoid stale timestamp reuse.
        obligation.last_assessed_on=self.assessment_date
        obligation.last_assessment=self.name
        obligation.obligation_status=self.assessment_result
        if self.remediation_action:
            obligation.remediation_action=self.remediation_action
        obligation.save(ignore_permissions=True)
