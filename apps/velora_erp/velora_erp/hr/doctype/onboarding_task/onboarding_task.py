from datetime import datetime, date, timezone
from velora import Document, throw
from velora.permissions import get_session

def _roles():
    s=get_session(); return s, set(getattr(s,"roles",()) or ())
class OnboardingTask(Document):
    def validate(self):
        if self.task_status == "Completed" and not self.completed_on:
            self.completed_on=datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
        if self.task_status == "Waived":
            if self.mandatory and not self.completion_notes:
                throw("Provide a reason before waiving a mandatory onboarding task.")
        if self.task_status == "Completed" and self.mandatory and not self.evidence_reference and self.task_category in {"Documentation","Compliance","IT Access","Equipment"}:
            throw("Provide an evidence reference for this mandatory control task.")
