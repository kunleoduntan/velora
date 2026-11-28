from velora import Document, throw


class RecruitmentSettings(Document):
    def validate(self):
        if self.ai_enabled and (not self.ai_provider or not self.ai_model or not self.ai_credential_reference):
            throw("AI assistance requires a provider, model and credential vault reference.")
        if self.default_interview_duration is not None and int(self.default_interview_duration) <= 0:
            throw("Default interview duration must be greater than zero.")
        if self.notification_reminder_hours is not None and int(self.notification_reminder_hours) < 0:
            throw("Interview reminder lead time cannot be negative.")
