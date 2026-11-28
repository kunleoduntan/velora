from velora import Document, throw

class GovernanceRisk(Document):
    def validate(self):
        for field in ("inherent_likelihood","inherent_impact","residual_likelihood","residual_impact"):
            value=getattr(self,field,None)
            if value not in (None,"") and (int(value)<1 or int(value)>5):
                throw(f"{field.replace('_',' ').title()} must be between 1 and 5.")
        self.inherent_score=int(self.inherent_likelihood or 0)*int(self.inherent_impact or 0)
        self.residual_likelihood=int(self.residual_likelihood or self.inherent_likelihood or 0)
        self.residual_impact=int(self.residual_impact or self.inherent_impact or 0)
        self.residual_score=self.residual_likelihood*self.residual_impact
        if self.treatment=="Mitigate" and self.risk_status in ("Treating","Monitoring") and not self.treatment_due_date:
            throw("Mitigated Governance Risks require a Treatment Due Date.")
