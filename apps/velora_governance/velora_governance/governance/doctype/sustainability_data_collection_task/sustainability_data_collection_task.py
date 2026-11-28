from velora import Document, get_list, throw
from velora_governance.governance.services.calendar_events import create_event, sync_event

class SustainabilityDataCollectionTask(Document):
    def validate(self):
        if self.data_point:
            points=get_list("Sustainability Data Point",filters=[["name","=",self.data_point]],fields=["governance_entity","metric","reporting_period"],limit=1)
            if points and (points[0].get("governance_entity")!=self.governance_entity or points[0].get("metric")!=self.metric or points[0].get("reporting_period")!=self.reporting_period):
                throw("Data Point must match the Task Entity, Metric and Reporting Period.")
        if self.task_status=="Completed" and not self.data_point:
            throw("Completed Data Collection Tasks require a Data Point.")

    def after_insert(self):
        if not self.calendar_event:
            event=create_event(event_type_name="Sustainability Data Collection Due",title=f"Sustainability Data Due: {self.metric}",entity=self.governance_entity,event_date=self.due_date,owner=self.responsible_owner,related_doctype="Sustainability Data Collection Task",related_record=self.name)
            if event:
                self.calendar_event=event
                self.save(ignore_permissions=True)

    def on_update(self):
        if self.calendar_event:
            status={"Completed":"Completed","Cancelled":"Cancelled","Overdue":"Overdue","In Progress":"In Progress"}.get(self.task_status,"Open")
            sync_event(self.calendar_event,title=f"Sustainability Data Due: {self.metric}",entity=self.governance_entity,event_date=self.due_date,status=status,related_doctype="Sustainability Data Collection Task",related_record=self.name,owner=self.responsible_owner)
