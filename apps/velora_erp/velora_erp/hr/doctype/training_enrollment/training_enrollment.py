from velora import Document, throw
class TrainingEnrollment(Document):
    def validate(self):
        if self.assessment_score is not None and not 0 <= float(self.assessment_score) <= 100: throw("Assessment Score must be between 0 and 100.")
        if self.training_cost is not None and float(self.training_cost) < 0: throw("Training Cost cannot be negative.")
        if self.status == "Completed" and self.attendance_status not in ("Present", "Partial"): throw("A completed enrolment requires recorded attendance.")

