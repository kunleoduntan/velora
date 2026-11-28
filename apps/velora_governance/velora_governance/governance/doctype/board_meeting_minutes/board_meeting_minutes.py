from velora import Document, get_doc, get_list, new_doc, throw

class BoardMeetingMinutes(Document):
    def validate(self):
        meetings = get_list("Board Meeting", filters=[["name", "=", self.meeting]], fields=["governance_entity", "board", "committee"], limit=1)
        if not meetings:
            throw("The selected Meeting could not be found.")
        meeting = meetings[0]
        if self.governance_entity and self.governance_entity != meeting.get("governance_entity"):
            throw("Minutes Governance Entity must match the Meeting.")
        self.governance_entity = meeting.get("governance_entity")
        if self.board and self.board != meeting.get("board"):
            throw("Minutes Board must match the Meeting.")
        self.board = meeting.get("board")
        if self.committee and self.committee != meeting.get("committee"):
            throw("Minutes Committee must match the Meeting.")
        self.committee = meeting.get("committee")
        versions = get_list("Board Meeting Minutes", filters=[["meeting", "=", self.meeting], ["minutes_version", "=", self.minutes_version]], fields=["name"], limit=20)
        if any(row.get("name") != self.name for row in versions):
            throw("Minutes Version must be unique for the selected Meeting.")
        sequences = set()
        for row in self.decisions or []:
            if row.decision_sequence in sequences:
                throw("Decision Sequence numbers must be unique within Minutes.")
            sequences.add(row.decision_sequence)
            if row.action_required:
                if not row.action_title or not row.action_owner or not row.action_due_date:
                    throw("Action-required decisions need an Action Title, Owner and Due Date.")
                if not row.action_type:
                    row.action_type = _default_action_type()
            if row.resolution:
                resolutions = get_list("Board Resolution", filters=[["name", "=", row.resolution]], fields=["meeting"], limit=1)
                if resolutions and resolutions[0].get("meeting") != self.meeting:
                    throw("A Minutes decision can only link a Resolution for the same Meeting.")
        if self.minutes_status == "Reviewed" and (not self.reviewed_by or not self.reviewed_on):
            throw("Reviewed Minutes require Reviewed By and Reviewed On.")
        if self.minutes_status == "Finalized" and (not self.document_reference or not self.finalized_by or not self.finalized_on):
            throw("Finalized Minutes require a file reference, Finalized By and Finalized On.")

    def after_insert(self):
        created = False
        for row in self.decisions or []:
            if not row.action_required or row.action_link:
                continue
            action = new_doc("Board Action", action_title=row.action_title, governance_entity=self.governance_entity,
                board=self.board, committee=self.committee, meeting=self.meeting, minutes=self.name,
                decision_sequence=row.decision_sequence, action_type=row.action_type, assigned_owner=row.action_owner,
                due_date=row.action_due_date, priority="Normal", action_status="Open", progress_percent=0)
            action.insert(ignore_permissions=True)
            row.action_link = action.name
            created = True
        if created:
            self.save(ignore_permissions=True)
        self._update_meeting_latest()

    def on_update(self):
        self._update_meeting_latest()

    def _update_meeting_latest(self):
        meeting = get_doc("Board Meeting", self.meeting, ignore_permissions=True)
        if meeting.minutes != self.name:
            meeting.minutes = self.name
            meeting.save(ignore_permissions=True)

def _default_action_type():
    rows = get_list("Board Action Type", fields=["name", "action_type_name"], limit=1000, ignore_permissions=True)
    return next((r["name"] for r in rows if r.get("action_type_name") == "Board Decision"), rows[0]["name"] if rows else None)
