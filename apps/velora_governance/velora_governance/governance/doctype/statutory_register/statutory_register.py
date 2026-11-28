from velora import Document, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class StatutoryRegister(Document):
    def validate(self):
        if self.review_frequency_months is not None and int(self.review_frequency_months)<=0:
            throw("Review Frequency (Months) must be greater than zero.")
        references=set()
        for row in self.entries or []:
            if row.record_reference and row.record_reference in references:
                throw("Register Record References must be unique within the Register.")
            if row.record_reference: references.add(row.record_reference)
            if row.effective_from and row.effective_to and row.effective_to<row.effective_from:
                throw("Register Entry Effective To cannot precede Effective From.")

    def after_insert(self):
        if self.next_review_date and not self.calendar_event:
            event=create_event(event_type_name="Statutory Register Review",title=f"Statutory register review: {self.register_title}",entity=self.governance_entity,event_date=self.next_review_date,owner=self.maintained_by,related_doctype="Statutory Register",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status="Completed" if self.register_status=="Inactive" or self.register_status=="Archived" else "Open"
            if self.register_status=="Under Review": status="In Progress"
            sync_event(self.calendar_event,title=f"Statutory register review: {self.register_title}",entity=self.governance_entity,event_date=self.next_review_date,status=status,related_doctype="Statutory Register",related_record=self.name,owner=self.maintained_by)
