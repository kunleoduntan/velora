from velora import Document, get_doc, get_list, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class GovernanceObligation(Document):
    def validate(self):
        requirements = get_list("Regulatory Requirement", filters=[["name", "=", self.requirement]], fields=["jurisdiction", "applicable_entity_type", "requirement_title"], limit=1)
        if not requirements:
            throw("The selected Regulatory Requirement could not be found.")
        entities = get_list("Governance Entity", filters=[["name", "=", self.governance_entity]], fields=["country", "entity_type"], limit=1)
        if not entities:
            throw("The selected Governance Entity could not be found.")
        requirement, entity = requirements[0], entities[0]
        if requirement.get("jurisdiction") and requirement.get("jurisdiction") != entity.get("country"):
            throw("The Regulatory Requirement jurisdiction does not match the Governance Entity country.")
        if requirement.get("applicable_entity_type") and requirement.get("applicable_entity_type") != entity.get("entity_type"):
            throw("The Regulatory Requirement is not applicable to this Entity Type.")

    def after_insert(self):
        if not self.calendar_event:
            event = create_event(event_type_name="Compliance Obligation Due", title=f"Compliance obligation: {self.obligation_period}", entity=self.governance_entity, event_date=self.due_date, owner=self.responsible_owner, related_doctype="Governance Obligation", related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status={"Compliant":"Completed","Closed":"Completed","Not Applicable":"Completed","Non-Compliant":"In Progress","Partially Compliant":"In Progress","Overdue":"Overdue","In Progress":"In Progress"}.get(self.obligation_status,"Open")
            sync_event(self.calendar_event,title=f"Compliance obligation: {self.obligation_period}",entity=self.governance_entity,event_date=self.due_date,status=status,related_doctype="Governance Obligation",related_record=self.name,owner=self.responsible_owner)
