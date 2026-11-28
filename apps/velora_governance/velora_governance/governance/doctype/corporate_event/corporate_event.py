from datetime import timedelta
from velora import Document, get_doc, get_list, new_doc, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class CorporateEvent(Document):
    def validate(self):
        if self.event_type and not self.effective_date:
            throw("Corporate Events require an Effective Date.")
        if self.filing_requirement:
            rows=get_list("Filing Requirement",filters=[["name","=",self.filing_requirement]],fields=["default_lead_days"],limit=1)
            if not rows: throw("The selected Filing Requirement could not be found.")

    def after_insert(self):
        if not self.corporate_filing and self.filing_requirement:
            req=get_list("Filing Requirement",filters=[["name","=",self.filing_requirement]],fields=["default_lead_days"],limit=1)
            lead=int(req[0].get("default_lead_days") or 0) if req else 0
            due=self.effective_date+timedelta(days=lead)
            filing=new_doc("Corporate Filing",governance_entity=self.governance_entity,filing_requirement=self.filing_requirement,filing_period=str(self.effective_date),due_date=due,responsible_owner="Company Secretary",filing_status="Draft",notes=f"Automatically created from Corporate Event {self.name}.")
            filing.insert(ignore_permissions=True)
            self.corporate_filing=filing.name
        if not self.calendar_event:
            event=create_event(event_type_name="Corporate Event",title=f"Corporate Event: {self.event_type}",entity=self.governance_entity,event_date=self.effective_date,related_doctype="Corporate Event",related_record=self.name)
            if event:self.calendar_event=event
        if self.corporate_filing or self.calendar_event:
            self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status={"Completed":"Completed","Cancelled":"Cancelled"}.get(self.event_status,"Open")
            sync_event(self.calendar_event,title=f"Corporate Event: {self.event_type}",entity=self.governance_entity,event_date=self.effective_date,status=status,related_doctype="Corporate Event",related_record=self.name)
