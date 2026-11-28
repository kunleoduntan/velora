from velora import Document, get_list, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class GovernancePolicy(Document):
    def validate(self):
        types=get_list("Governance Policy Type",filters=[["name","=",self.policy_type]],fields=["review_frequency_months","acknowledgement_required"],limit=1)
        if types:
            if self.review_frequency_months in (None,""):
                self.review_frequency_months=types[0].get("review_frequency_months") or 12
            if not self.acknowledgement_required and types[0].get("acknowledgement_required"):
                self.acknowledgement_required=1
        if int(self.review_frequency_months or 0)<=0:
            throw("Policy Review Frequency Months must be greater than zero.")
        duplicates=get_list("Governance Policy",filters=[["governance_entity","=",self.governance_entity],["policy_code","=",self.policy_code]],fields=["name"],limit=20)
        if any(row.get("name")!=self.name for row in duplicates):
            throw("Policy Code must be unique within the Governance Entity.")
        if self.policy_status=="Active" and (not self.document_reference or not self.effective_date):
            throw("Active Policies require a document reference and Effective Date.")
        if self.acknowledgement_required:
            seen=set()
            for row in self.acknowledgements or []:
                key=row.board_member or row.employee_or_recipient
                if key in seen: throw("A recipient can only acknowledge a Policy version once.")
                if key: seen.add(key)

    def after_insert(self):
        if self.next_review_date and not self.calendar_event:
            event=create_event(event_type_name="Policy Review",title=f"Policy Review: {self.policy_title}",entity=self.governance_entity,event_date=self.next_review_date,owner=self.policy_owner,related_doctype="Governance Policy",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status={"Under Review":"In Progress","Superseded":"Completed","Archived":"Completed"}.get(self.policy_status,"Open")
            sync_event(self.calendar_event,title=f"Policy Review: {self.policy_title}",entity=self.governance_entity,event_date=self.next_review_date,status=status,related_doctype="Governance Policy",related_record=self.name,owner=self.policy_owner)
