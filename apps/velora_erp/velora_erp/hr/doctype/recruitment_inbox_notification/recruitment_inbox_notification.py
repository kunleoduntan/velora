from velora import Document, throw


class RecruitmentInboxNotification(Document):
    def validate(self):
        if not self.recipient or not self.subject or not self.message or not self.event_type:
            throw("Recipient, subject, message and event type are required.")
        if self.notification_status == "Read" and not self.read_at:
            # Read timestamp is set by the inbox action; reject incomplete manual transitions.
            throw("A read notification must have a read timestamp.")
