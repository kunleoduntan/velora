from velora import Document, get_list, throw

class SustainabilitySettings(Document):
    def validate(self):
        rows=get_list("Sustainability Settings",fields=["name"],limit=20,ignore_permissions=True)
        if any(row.get("name")!=self.name for row in rows):
            throw("Only one Sustainability Settings record is allowed per company.")
        for field in ("impact_materiality_threshold","financial_materiality_threshold"):
            value=int(getattr(self,field) or 3)
            if not 1<=value<=5:throw(f"{field.replace('_',' ').title()} must be between 1 and 5.")
        readiness=int(self.report_readiness_threshold or 100)
        if readiness<0 or readiness>100:throw("Report Readiness Threshold must be between 0 and 100.")
