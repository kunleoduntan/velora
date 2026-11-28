from velora import Document, get_doc, get_list, throw


class SASBMetricResponse(Document):
    """The entity's answer to one SASB metric for one period. A metric that is not reported is explained, never left blank."""

    def validate(self):
        m = get_doc("SASB Metric", self.sasb_metric, ignore_permissions=True)
        self.industry = m.industry
        if self.data_point:
            dp = get_doc("Sustainability Data Point", self.data_point, ignore_permissions=True)
            if dp.governance_entity != self.governance_entity or dp.reporting_period != self.reporting_period:
                throw("The data point belongs to a different entity or period.")
            if self.value is None and dp.value is not None:
                self.value = dp.value
        st = self.response_status or "Not started"
        if st == "Reported" and self.value is None and not (self.text_response or "").strip():
            throw("A reported metric needs a value or a narrative answer.")
        if st in ("Omitted", "Not applicable") and not (self.omission_reason or "").strip():
            throw("Explain why the metric is omitted or not applicable.")
        dup = get_list("SASB Metric Response", filters=[["governance_entity", "=", self.governance_entity], ["reporting_period", "=", self.reporting_period], ["sasb_metric", "=", self.sasb_metric], ["name", "!=", self.name or ""]], fields=["name"], limit=1, ignore_permissions=True)
        if dup:
            throw("This metric already has a response for the entity and period.")
