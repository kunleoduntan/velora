from velora import Document, get_doc, get_list, throw

class BoardResolution(Document):
    def validate(self):
        if self.meeting:
            meetings = get_list("Board Meeting", filters=[["name", "=", self.meeting]], fields=["governance_entity", "board", "committee"], limit=1)
            if not meetings:
                throw("The selected Meeting could not be found.")
            meeting = meetings[0]
            if self.governance_entity and self.governance_entity != meeting.get("governance_entity"):
                throw("Resolution Governance Entity must match the Meeting.")
            self.governance_entity = meeting.get("governance_entity")
            if self.board and self.board != meeting.get("board"):
                throw("Resolution Board must match the Meeting.")
            self.board = meeting.get("board")
            if self.committee and self.committee != meeting.get("committee"):
                throw("Resolution Committee must match the Meeting.")
            self.committee = meeting.get("committee")
        if self.committee and self.board:
            rows = get_list("Board Committee", filters=[["name", "=", self.committee]], fields=["board", "governance_entity"], limit=1)
            if rows and rows[0].get("board") != self.board:
                throw("Resolution Committee must belong to the selected Board.")
            if rows and rows[0].get("governance_entity") != self.governance_entity:
                throw("Resolution Committee must belong to the selected Governance Entity.")
        types = get_list("Board Resolution Type", filters=[["name", "=", self.resolution_type]], fields=["approval_threshold_percent"], limit=1)
        if types:
            self.approval_threshold_percent = int(types[0].get("approval_threshold_percent") or 0)
        threshold = int(self.approval_threshold_percent or 0)
        if threshold < 0 or threshold > 100:
            throw("Approval Threshold Percent must be between 0 and 100.")
        seen = set(); counts = {"For":0,"Against":0,"Abstain":0}
        for row in self.votes or []:
            if row.board_member in seen:
                throw("A Board Member can only vote once on a Resolution.")
            seen.add(row.board_member)
            counts[row.vote] = counts.get(row.vote,0) + 1
        if seen and (self.board or self.committee):
            eligible = set()
            if self.committee:
                committee = get_doc("Board Committee", self.committee)
                eligible = {row.board_member for row in committee.members or [] if row.membership_status == "Active"}
            elif self.board:
                appointments = get_list("Board Appointment", filters=[["board", "=", self.board], ["appointment_status", "=", "Active"]], fields=["board_member"], limit=1000)
                eligible = {row.get("board_member") for row in appointments}
            if eligible and not seen <= eligible:
                throw("Voting records may only include eligible active Board or Committee Members.")
        self.votes_for = counts.get("For",0)
        self.votes_against = counts.get("Against",0)
        self.abstentions = counts.get("Abstain",0)
        self.total_votes = self.votes_for + self.votes_against + self.abstentions
        denominator = self.votes_for + self.votes_against
        if denominator == 0:
            self.vote_result = "No Votes"
        else:
            percent_for = self.votes_for * 100.0 / denominator
            self.vote_result = "Met" if percent_for >= threshold else "Not Met"
        if self.resolution_method == "Voting":
            if self.resolution_status in ("Adopted", "Rejected") and self.voting_status != "Closed":
                throw("A Voting Resolution must have closed voting before it can be Adopted or Rejected.")
            if self.resolution_status == "Adopted" and (self.vote_result != "Met" or denominator == 0):
                throw("A Voting Resolution cannot be Adopted unless its configured threshold is met.")
            if self.resolution_status == "Rejected" and (self.vote_result != "Not Met" or denominator == 0):
                throw("A Voting Resolution cannot be Rejected when its configured threshold is met or no votes were cast.")
        if self.resolution_status in ("Adopted", "Rejected") and not self.resolution_date:
            throw("Adopted or Rejected Resolutions require a Resolution Date.")
