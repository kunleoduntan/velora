from velora import Document, get_list, throw

class BoardCommittee(Document):
    def validate(self):
        if self.quorum_required is not None and int(self.quorum_required) < 0:
            throw("Committee Quorum Required cannot be negative.")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            throw("Committee Effective To cannot be earlier than Effective From.")
        if self.board and self.governance_entity:
            rows = get_list("Board", filters=[["name", "=", self.board]], fields=["governance_entity"], limit=1)
            if rows and rows[0].get("governance_entity") != self.governance_entity:
                throw("The selected Board belongs to a different Governance Entity.")
        seen = set(); chairs = 0
        for row in self.members or []:
            if row.board_member in seen:
                throw("A Board Member can only be listed once in a Committee.")
            seen.add(row.board_member)
            if row.committee_role == "Chair" and row.membership_status == "Active":
                chairs += 1
            if row.effective_from and row.effective_to and row.effective_to < row.effective_from:
                throw("Committee member Effective To cannot be earlier than Effective From.")
        if chairs > 1:
            throw("A Committee can have only one active Chair.")
        active_members = {row.board_member for row in self.members or [] if row.membership_status == "Active"}
        if self.committee_status == "Active" and self.chair and self.chair not in active_members:
            throw("The Committee Chair must be an active Committee Member.")
        if self.committee_status == "Active" and self.secretary and self.secretary not in active_members:
            throw("The Committee Secretary must be an active Committee Member.")
        if self.quorum_required and active_members and int(self.quorum_required) > len(active_members):
            throw("Committee Quorum Required cannot exceed active Committee membership.")
