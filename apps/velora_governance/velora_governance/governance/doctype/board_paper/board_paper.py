from velora import Document, get_list, throw
from datetime import date, datetime

def _day(value):
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    if isinstance(value, str) and value: return date.fromisoformat(value[:10])
    return None

class BoardPaper(Document):
    def validate(self):
        rows = get_list("Board Meeting", filters=[["name", "=", self.meeting]], fields=["governance_entity", "board", "committee", "scheduled_start"], limit=1)
        if not rows:
            throw("The selected Meeting could not be found.")
        meeting = rows[0]
        if self.governance_entity and self.governance_entity != meeting.get("governance_entity"):
            throw("Board Paper Governance Entity must match the Meeting.")
        self.governance_entity = meeting.get("governance_entity")
        if self.board and self.board != meeting.get("board"):
            throw("Board Paper Board must match the Meeting.")
        self.board = meeting.get("board")
        if self.committee and self.committee != meeting.get("committee"):
            throw("Board Paper Committee must match the Meeting.")
        self.committee = meeting.get("committee")
        meeting_day = _day(meeting.get("scheduled_start"))
        deadline = _day(self.circulation_deadline)
        if deadline and meeting_day and deadline > meeting_day:
            throw("Circulation Deadline cannot be after the Meeting date.")
        if self.paper_status == "Circulated" and not self.submission_date:
            throw("A circulated Board Paper must have a Submission Date.")
