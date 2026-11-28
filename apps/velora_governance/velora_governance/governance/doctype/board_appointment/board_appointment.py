from velora import Document, get_list, throw

class BoardAppointment(Document):
    def validate(self):
        start = self.term_start_date or self.effective_date or self.appointment_date
        end = self.term_end_date
        if start and end and end < start:
            throw("Term End Date cannot be earlier than Term Start Date.")
        exits = [d for d in (self.resignation_date, self.retirement_date, self.removal_date) if d]
        if len(exits) > 1:
            throw("Only one exit date may be recorded: resignation, retirement or removal.")
        if exits and start and exits[0] < start:
            throw("An appointment exit date cannot precede the appointment term start.")
        if self.board and self.governance_entity:
            boards = get_list("Board", filters=[["name", "=", self.board]], fields=["governance_entity"], limit=1)
            if boards and boards[0].get("governance_entity") != self.governance_entity:
                throw("The selected Board belongs to a different Governance Entity.")
        if self.board_member and self.board and self.appointment_status in ("Draft", "Active"):
            filters = [["board_member", "=", self.board_member], ["board", "=", self.board], ["appointment_status", "in", ["Draft", "Active"]]]
            rows = get_list("Board Appointment", filters=filters, fields=["name"], limit=20)
            if any(row.get("name") != self.name for row in rows):
                throw("This Board Member already has a draft or active appointment on this Board.")
