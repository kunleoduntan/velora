from velora import Document, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class GovernanceControl(Document):
    def validate(self):
        if self.next_test_date and self.last_tested and self.next_test_date<self.last_tested:
            throw("Next Test Date cannot precede Last Tested.")

    def after_insert(self):
        if self.next_test_date and not self.calendar_event:
            event=create_event(event_type_name="Governance Control Testing",title=f"Control Test Due: {self.control_name}",entity=self.governance_entity,event_date=self.next_test_date,owner=self.control_owner,related_doctype="Governance Control",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status="Completed" if self.control_status=="Inactive" else "In Progress" if self.control_status in ("Review Due","Under Remediation") else "Open"
            sync_event(self.calendar_event,title=f"Control Test Due: {self.control_name}",entity=self.governance_entity,event_date=self.next_test_date,status=status,related_doctype="Governance Control",related_record=self.name,owner=self.control_owner)
