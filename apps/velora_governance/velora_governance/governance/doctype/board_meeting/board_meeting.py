from datetime import date, datetime
from velora import Document, get_doc, get_list, new_doc, throw

def _meeting_day(value):
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    if isinstance(value, str) and value: return date.fromisoformat(value[:10])
    return None

class BoardMeeting(Document):
    def validate(self):
        if self.scheduled_start and self.scheduled_end and self.scheduled_end <= self.scheduled_start:
            throw("Scheduled End must be later than Scheduled Start.")
        if self.committee:
            rows = get_list("Board Committee", filters=[["name", "=", self.committee]], fields=["board", "governance_entity", "quorum_required"], limit=1)
            if not rows:
                throw("The selected Committee could not be found.")
            committee = rows[0]
            if self.board and self.board != committee.get("board"):
                throw("The selected Committee belongs to a different Board.")
            self.board = committee.get("board")
            if self.governance_entity and self.governance_entity != committee.get("governance_entity"):
                throw("The selected Committee belongs to a different Governance Entity.")
            self.governance_entity = committee.get("governance_entity")
            if self.quorum_required in (None, ""):
                self.quorum_required = committee.get("quorum_required") or 1
        elif not self.board:
            throw("Choose a Board or a Committee for this meeting.")
        if self.board and self.governance_entity:
            rows = get_list("Board", filters=[["name", "=", self.board]], fields=["governance_entity", "quorum_required"], limit=1)
            if rows and rows[0].get("governance_entity") != self.governance_entity:
                throw("The selected Board belongs to a different Governance Entity.")
            if self.quorum_required in (None, "") and rows:
                self.quorum_required = rows[0].get("quorum_required") or 1
        if self.quorum_required is not None and int(self.quorum_required) < 0:
            throw("Quorum Required cannot be negative.")
        agenda_sequences = set()
        for item in self.agenda_items or []:
            if item.sequence in agenda_sequences:
                throw("Agenda Sequence numbers must be unique within a meeting.")
            agenda_sequences.add(item.sequence)
            if item.duration_minutes is not None and int(item.duration_minutes) < 0:
                throw("Agenda item Duration cannot be negative.")
            if item.board_paper:
                rows = get_list("Board Paper", filters=[["name", "=", item.board_paper]], fields=["meeting"], limit=1)
                if rows and rows[0].get("meeting") != self.name:
                    throw("An Agenda Item can only link a Board Paper for the same meeting.")
        attendee_names = set(); present_members = set()
        for row in self.attendance or []:
            if row.attendee_type == "Member" and not row.board_member:
                throw("Member attendance requires a Board Member.")
            if row.attendee_type == "Guest" and not row.guest_name:
                throw("Guest attendance requires a Guest Name.")
            if row.board_member and row.board_member in attendee_names:
                throw("A Board Member can only appear once in Meeting Attendance.")
            if row.board_member: attendee_names.add(row.board_member)
            if row.attendance_status == "Present" and row.attendee_type == "Member" and row.board_member:
                present_members.add(row.board_member)
        if self.committee:
            cm = get_doc("Board Committee", self.committee)
            eligible = {row.board_member for row in cm.members or [] if row.membership_status == "Active"}
            present_members &= eligible
        elif self.board:
            active = get_list("Board Appointment", filters=[["board", "=", self.board], ["appointment_status", "=", "Active"]], fields=["board_member"], limit=1000)
            eligible = {row.get("board_member") for row in active}
            present_members &= eligible
        self.quorum_met = int(len(present_members) >= int(self.quorum_required or 1))
        if self.meeting_status == "Completed" and not self.quorum_met:
            throw("A meeting cannot be marked Completed without meeting its configured quorum.")

    def after_insert(self):
        if not self.calendar_event and self.scheduled_start:
            event_type_label = "Committee Meeting" if self.committee else "Board Meeting"
            event_types = get_list("Governance Event Type", fields=["name", "event_type_name", "default_reminder_days"], limit=1000)
            event_type = next((row for row in event_types if row.get("event_type_name") == event_type_label), None)
            if event_type:
                event = new_doc("Governance Calendar Event", event_title=self.meeting_title, event_type=event_type["name"],
                    governance_entity=self.governance_entity, board=self.board, event_date=_meeting_day(self.scheduled_start),
                    responsible_person=self.secretary or self.chair, reminder_days=event_type.get("default_reminder_days"),
                    event_status="Open", related_doctype="Board Meeting", related_record=self.name)
                event.insert(ignore_permissions=True)
                self.calendar_event = event.name
                self.save(ignore_permissions=True)

    def on_update(self):
        if not self.calendar_event:
            return
        event = get_doc("Governance Calendar Event", self.calendar_event, ignore_permissions=True)
        event.event_title = self.meeting_title
        event.governance_entity = self.governance_entity
        event.board = self.board
        event.event_date = _meeting_day(self.scheduled_start)
        event.related_doctype = "Board Meeting"
        event.related_record = self.name
        event.event_status = {"Cancelled":"Cancelled", "Completed":"Completed", "In Progress":"In Progress"}.get(self.meeting_status, "Open")
        event.save(ignore_permissions=True)
