from velora import Document, get_doc, get_list, throw

class SustainabilityDataPoint(Document):
    def validate(self):
        from velora_governance.governance.services.assurance_lock import assert_unlocked
        assert_unlocked(self.governance_entity, self.reporting_period, "This Data Point")
        if not self.is_new():
            stored = get_list("Sustainability Data Point", filters=[["name", "=", self.name]], fields=["reporting_period"], limit=1, ignore_permissions=True)
            if stored and stored[0].get("reporting_period") != self.reporting_period:
                assert_unlocked(self.governance_entity, stored[0].get("reporting_period"), "This Data Point")
        metrics=get_list("Sustainability Metric",filters=[["name","=",self.metric]],fields=["default_unit","data_type"],limit=1)
        if not metrics:throw("The selected Sustainability Metric could not be found.")
        metric=metrics[0]
        if metric.get("default_unit") and self.unit!=metric.get("default_unit"):
            throw("Data Point Unit must match the Metric Default Unit.")
        if metric.get("data_type") and self.data_type!=metric.get("data_type"):
            throw("Data Point Data Type must match the Metric Data Type.")
        if self.data_type in ("Numeric","Percentage","Currency") and self.value is None:
            throw("Numeric, Percentage and Currency data points require a Value.")
        if self.data_type=="Text" and not self.text_value:
            throw("Text data points require a Text Value.")
        if self.data_type=="Boolean" and self.boolean_value is None:
            throw("Boolean data points require a Boolean Value.")

    def after_insert(self):
        if self.data_type in ("Numeric","Percentage","Currency"):
            targets=get_list("Sustainability Target",filters=[["governance_entity","=",self.governance_entity],["metric","=",self.metric]],fields=["name"],limit=1000,ignore_permissions=True)
            for row in targets:
                target=get_doc("Sustainability Target",row["name"],ignore_permissions=True)
                target.current_value=self.value
                target.save(ignore_permissions=True)
        tasks=get_list("Sustainability Data Collection Task",filters=[["governance_entity","=",self.governance_entity],["metric","=",self.metric],["reporting_period","=",self.reporting_period],["task_status","in",["Open","In Progress"]]],fields=["name"],limit=1000,ignore_permissions=True)
        for row in tasks:
            task=get_doc("Sustainability Data Collection Task",row["name"],ignore_permissions=True)
            task.data_point=self.name;task.task_status="Completed";task.save(ignore_permissions=True)

    def before_delete(self):
        from velora_governance.governance.services.assurance_lock import assert_unlocked
        assert_unlocked(self.governance_entity, self.reporting_period, "This Data Point")
