from velora import Document, throw
class ExternalAttendancePunch(Document):
    def validate(self):
        if not self.external_event_key or len(str(self.external_event_key))!=64: throw("External event key must be a SHA-256 key.")
        if not self.external_user_id or not self.punch_datetime: throw("External user ID and punch timestamp are required.")
        if self.processing_status=="Processed" and not self.attendance: throw("Processed punches must link to an Attendance record.")
