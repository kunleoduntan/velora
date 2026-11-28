from velora import Document, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class RegulatoryCorrespondence(Document):
    def validate(self):
        if self.response_due_date and self.correspondence_date and self.response_due_date < self.correspondence_date:
            throw("Response Due Date cannot precede the Correspondence Date.")
        if self.response_date and self.correspondence_date and self.response_date < self.correspondence_date:
            throw("Response Date cannot precede the Correspondence Date.")
        if self.correspondence_status in ("Responded","Closed") and not self.response_date:
            throw("Responded or Closed correspondence requires a Response Date.")

    def after_insert(self):
        if self.direction == "Received" and self.response_due_date and not self.calendar_event:
            event=create_event(event_type_name="Regulatory Correspondence Due",title=f"Regulatory response due: {self.subject}",entity=self.governance_entity,event_date=self.response_due_date,owner=self.responsible_owner,related_doctype="Regulatory Correspondence",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status={"Responded":"Completed","Closed":"Completed","Overdue":"Overdue","In Progress":"In Progress"}.get(self.correspondence_status,"Open")
            sync_event(self.calendar_event,title=f"Regulatory response due: {self.subject}",entity=self.governance_entity,event_date=self.response_due_date,status=status,related_doctype="Regulatory Correspondence",related_record=self.name,owner=self.responsible_owner)
