from velora import Document, get_doc, get_list, throw
from velora import naming
from velora_governance.governance.services.skills_matrix import calculate_matrix

class BoardSkillsMatrix(Document):
    def validate(self):
        seen = set()
        for row in self.requirements or []:
            if row.skill in seen:
                throw("A skill can only appear once in the requirements for this assessment.")
            seen.add(row.skill)
            if row.minimum_coverage is not None and int(row.minimum_coverage) < 0:
                throw("Minimum Coverage cannot be negative.")
        if not self.board:
            return
        appointments = get_list("Board Appointment", filters=[["board", "=", self.board], ["appointment_status", "=", "Active"]], fields=["board_member"], limit=1000)
        members = sorted({row.get("board_member") for row in appointments if row.get("board_member")})
        member_skills = []
        for member_name in members:
            member_doc = get_doc("Board Member", member_name)
            if member_doc.profile_status != "Active":
                continue
            for skill_row in member_doc.skills or []:
                if skill_row.skill and skill_row.skill_level:
                    member_skills.append({"member": member_name, "skill": skill_row.skill, "skill_level": skill_row.skill_level})
        levels = get_list("Governance Skill Level", fields=["name", "level_order"], limit=1000)
        level_order = {row["name"]: int(row.get("level_order") or 0) for row in levels}
        calculated = calculate_matrix([row.as_dict() if hasattr(row, "as_dict") else {"skill":row.skill,"minimum_coverage":row.minimum_coverage,"required_skill_level":row.required_skill_level,"critical":row.critical,"notes":row.notes} for row in self.requirements or []], member_skills, level_order)
        self.results[:] = []
        for idx, result in enumerate(calculated, start=1):
            child = self.append("results", result)
            # Framework links child rows before parent validation; these result rows are
            # calculated during validate(), so attach them explicitly for this lifecycle.
            child.name = naming.make_name(child.meta, child)
            child.parent = self.name
            child.parenttype = self.doctype
            child.parentfield = "results"
            child.idx = idx
            child.owner = self.owner
            child.creation = self.creation
            child.modified = self.modified
            child.modified_by = self.modified_by
            child.docstatus = self.docstatus
        if calculated:
            self.assessment_status = "Calculated"
