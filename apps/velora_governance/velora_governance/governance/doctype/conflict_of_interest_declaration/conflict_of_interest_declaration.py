from velora import Document, get_list, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class ConflictOfInterestDeclaration(Document):
    def validate(self):
        if self.board and self.governance_entity:
            rows=get_list("Board",filters=[["name","=",self.board]],fields=["governance_entity"],limit=1)
            if rows and rows[0].get("governance_entity")!=self.governance_entity:
                throw("Conflict Declaration Board must belong to the selected Entity.")
        if self.committee and self.board:
            rows=get_list("Board Committee",filters=[["name","=",self.committee]],fields=["board","governance_entity"],limit=1)
            if rows and rows[0].get("board")!=self.board:
                throw("Conflict Declaration Committee must belong to the selected Board.")
        if self.declaration_status in ("Under Review","Mitigation Required","Cleared","Escalated","Closed") and (not self.reviewed_by or not self.reviewed_on):
            throw("Reviewed Conflict Declarations require Reviewed By and Reviewed On.")
        if self.declaration_status=="Mitigation Required" and not self.mitigation_plan:
            throw("Mitigation Required declarations must have a Mitigation Plan.")

    def after_insert(self):
        if self.renewal_date and not self.calendar_event:
            event=create_event(event_type_name="Conflict Declaration Renewal",title=f"Conflict Declaration Renewal: {self.board_member}",entity=self.governance_entity,event_date=self.renewal_date,owner=self.board_member,related_doctype="Conflict of Interest Declaration",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status="Completed" if self.declaration_status in ("Cleared","Closed") else "In Progress" if self.declaration_status in ("Under Review","Mitigation Required","Escalated") else "Open"
            sync_event(self.calendar_event,title=f"Conflict Declaration Renewal: {self.board_member}",entity=self.governance_entity,event_date=self.renewal_date,status=status,related_doctype="Conflict of Interest Declaration",related_record=self.name,owner=self.board_member)
