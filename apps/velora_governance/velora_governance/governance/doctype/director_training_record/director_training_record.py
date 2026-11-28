from velora import Document, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class DirectorTrainingRecord(Document):
    def validate(self):
        if float(self.hours or 0)<0 or float(self.cpd_credits or 0)<0:
            throw("Training Hours and CPD Credits cannot be negative.")
        if self.training_status=="Completed" and not self.training_date:
            throw("Completed Training Records require a Training Date.")

    def after_insert(self):
        if self.expiry_date and not self.calendar_event:
            event=create_event(event_type_name="Governance Training",title=f"Training Expiry: {self.training_title}",entity=None,event_date=self.expiry_date,owner=self.board_member,related_doctype="Director Training Record",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status="Completed" if self.training_status in ("Expired","Cancelled") else "Open"
            sync_event(self.calendar_event,title=f"Training Expiry: {self.training_title}",event_date=self.expiry_date,status=status,related_doctype="Director Training Record",related_record=self.name,owner=self.board_member)
