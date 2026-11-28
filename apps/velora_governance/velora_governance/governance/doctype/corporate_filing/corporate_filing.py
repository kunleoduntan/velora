from velora import Document, get_doc, get_list, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class CorporateFiling(Document):
    def validate(self):
        requirements=get_list("Filing Requirement",filters=[["name","=",self.filing_requirement]],fields=["authority","jurisdiction","entity_type","filing_requirement_name"],limit=1)
        if not requirements: throw("The selected Filing Requirement could not be found.")
        entities=get_list("Governance Entity",filters=[["name","=",self.governance_entity]],fields=["country","entity_type"],limit=1)
        if not entities: throw("The selected Governance Entity could not be found.")
        req,entity=requirements[0],entities[0]
        if req.get("jurisdiction") and req.get("jurisdiction") != entity.get("country"):
            throw("The Filing Requirement jurisdiction does not match the Governance Entity country.")
        if req.get("entity_type") and req.get("entity_type") != entity.get("entity_type"):
            throw("The Filing Requirement is not applicable to this Entity Type.")
        if self.filing_status == "Submitted" and (not self.submitted_on or not self.filing_reference):
            throw("Submitted filings require a Submission Date and Filing Reference.")
        if self.filing_status == "Accepted" and not self.accepted_on:
            throw("Accepted filings require an Accepted Date.")

    def after_insert(self):
        if not self.calendar_event:
            event=create_event(event_type_name="Corporate Filing Due",title=f"Filing due: {self.filing_requirement}",entity=self.governance_entity,event_date=self.due_date,owner=self.responsible_owner,related_doctype="Corporate Filing",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status={"Accepted":"Completed","Not Required":"Completed","Cancelled":"Cancelled","Overdue":"Overdue","Submitted":"In Progress","Rejected":"In Progress"}.get(self.filing_status,"Open")
            sync_event(self.calendar_event,title=f"Filing due: {self.filing_requirement}",entity=self.governance_entity,event_date=self.due_date,status=status,related_doctype="Corporate Filing",related_record=self.name,owner=self.responsible_owner)
