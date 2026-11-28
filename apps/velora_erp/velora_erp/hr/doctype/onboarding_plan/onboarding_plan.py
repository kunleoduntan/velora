from datetime import date
from velora import Document, throw

def _d(v): return v if isinstance(v,date) else (date.fromisoformat(str(v)[:10]) if v else None)
class OnboardingPlan(Document):
    def validate(self):
        if _d(self.target_completion_date) and _d(self.start_date) and _d(self.target_completion_date) < _d(self.start_date):
            throw("Target completion date cannot be before the employment start date.")
        pct=float(self.completion_percentage or 0)
        if pct < 0 or pct > 100: throw("Completion percentage must be between 0 and 100.")
        if self.plan_status == "Completed" and pct < 100:
            throw("An onboarding plan cannot be completed until all tasks are complete (100%).")
