from velora import Document, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class RelatedPartyInterest(Document):
    def validate(self):
        if self.effective_date and self.review_date and self.review_date<self.effective_date:
            throw("Review Date cannot precede Effective Date.")

    def after_insert(self):
        if self.review_date and not self.calendar_event:
            event=create_event(event_type_name="Conflict Declaration Renewal",title=f"Related Party Interest Review: {self.related_party_name}",entity=self.governance_entity,event_date=self.review_date,owner=self.board_member,related_doctype="Related Party Interest",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status="Completed" if self.interest_status in ("Closed","Archived") else "In Progress" if self.interest_status=="Under Review" else "Open"
            sync_event(self.calendar_event,title=f"Related Party Interest Review: {self.related_party_name}",entity=self.governance_entity,event_date=self.review_date,status=status,related_doctype="Related Party Interest",related_record=self.name,owner=self.board_member)
