from velora import Document, throw
class EmployeeCompetencyAssessment(Document):
    def validate(self):
        current=int(self.current_level or 0); required=int(self.required_level or 0)
        if current < 1 or current > 5: throw("Current proficiency level must be between 1 and 5.")
        if required and (required < 1 or required > 5): throw("Required proficiency level must be between 1 and 5.")
        self.gap_level=max(required-current,0) if required else 0
        if self.status in ("Submitted","Confirmed") and not str(self.evidence or "").strip():
            throw("Provide evidence or examples before submitting a competency assessment.")
