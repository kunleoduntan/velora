from velora import Document, get_list, throw

class BoardAction(Document):
    def validate(self):
        if self.meeting:
            meetings = get_list("Board Meeting", filters=[["name", "=", self.meeting]], fields=["governance_entity", "board", "committee"], limit=1)
            if meetings:
                meeting = meetings[0]
                self.governance_entity = self.governance_entity or meeting.get("governance_entity")
                self.board = self.board or meeting.get("board")
                self.committee = self.committee or meeting.get("committee")
        if self.minutes and self.meeting:
            minutes = get_list("Board Meeting Minutes", filters=[["name", "=", self.minutes]], fields=["meeting"], limit=1)
            if minutes and minutes[0].get("meeting") != self.meeting:
                throw("Board Action Minutes must belong to the selected Meeting.")
        progress = int(self.progress_percent or 0)
        if progress < 0 or progress > 100:
            throw("Progress Percent must be between 0 and 100.")
        if self.action_status == "Completed":
            if not self.completion_date:
                throw("Completed Board Actions require a Completion Date.")
            self.progress_percent = 100
        for update in self.updates or []:
            if update.progress_percent is not None and (int(update.progress_percent) < 0 or int(update.progress_percent) > 100):
                throw("Action Update Progress Percent must be between 0 and 100.")
