from velora import Document, get_list, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class AnnualReturn(Document):
    def validate(self):
        rows=get_list("Annual Return",filters=[["governance_entity","=",self.governance_entity],["reporting_year","=",self.reporting_year]],fields=["name"],limit=20)
        if any(row.get("name")!=self.name for row in rows):
            throw("Only one Annual Return may be maintained per Entity and Reporting Year.")
        if self.annual_return_status=="Filed" and (not self.filed_on or not self.filing_reference):
            throw("Filed Annual Returns require a Filed On date and Filing Reference.")

    def after_insert(self):
        if not self.calendar_event:
            event=create_event(event_type_name="Annual Return Due",title=f"Annual Return due: {self.reporting_year}",entity=self.governance_entity,event_date=self.due_date,related_doctype="Annual Return",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status={"Filed":"Completed","Cancelled":"Cancelled","Overdue":"Overdue","Submitted":"In Progress"}.get(self.annual_return_status,"Open")
            sync_event(self.calendar_event,title=f"Annual Return due: {self.reporting_year}",entity=self.governance_entity,event_date=self.due_date,status=status,related_doctype="Annual Return",related_record=self.name)
