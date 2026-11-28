from velora import Document, throw

class GovernanceCalendarEvent(Document):
    def validate(self):
        if self.reminder_days is not None and int(self.reminder_days) < 0:
            throw("Reminder Days cannot be negative.")
