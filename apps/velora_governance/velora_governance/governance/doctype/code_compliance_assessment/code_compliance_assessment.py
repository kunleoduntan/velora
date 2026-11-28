from velora import Document, get_doc, throw


class CodeComplianceAssessment(Document):
    """An apply-and-explain assessment of an entity against a governance code. A new one starts with one response per principle."""

    def validate(self):
        if self.is_new() and not (self.get("responses") or []):
            code = get_doc("Governance Code", self.governance_code, ignore_permissions=True)
            for p in sorted(code.get("principles") or [], key=lambda r: r.principle_number):
                self.append("responses", {"principle_number": p.principle_number, "part": p.part, "title": p.title, "status": "Not assessed"})
        if self.is_new() and not (self.get("practice_responses") or []):
            code = get_doc("Governance Code", self.governance_code, ignore_permissions=True)
            for p in code.get("practices") or []:
                self.append("practice_responses", {"principle_number": p.principle_number, "reference": p.reference, "requirement": p.requirement, "status": "Not assessed"})
        self._roll_up_practices()
        counts = {"Applied": 0, "Applied in part": 0, "Explained (not applied)": 0, "Not assessed": 0}
        for r in self.get("responses") or []:
            status = r.status or "Not assessed"
            counts[status] = counts.get(status, 0) + 1
            if status in ("Applied in part", "Explained (not applied)") and not (r.how_applied_or_explanation or "").strip():
                throw(f"Principle {r.principle_number} ({r.title}): give the explanation. Apply-and-explain means a departure is always explained.")
        total = sum(counts.values())
        self.applied_count, self.partial_count = counts["Applied"], counts["Applied in part"]
        self.explained_count, self.not_assessed_count = counts["Explained (not applied)"], counts["Not assessed"]
        self.application_percent = round(100.0 * counts["Applied"] / total, 2) if total else 0.0

    def _roll_up_practices(self):
        """Count practice-level answers; a departure (partly applied or explained) needs its explanation, as at principle level."""
        applied = assessed = in_scope = 0
        for r in self.get("practice_responses") or []:
            status = r.status or "Not assessed"
            if status == "Not applicable":
                continue
            in_scope += 1
            if status != "Not assessed":
                assessed += 1
            if status == "Applied":
                applied += 1
            if status in ("Applied in part", "Explained (not applied)") and not (r.how_applied_or_explanation or "").strip():
                throw(f"Practice {r.reference}: give the explanation. Apply-and-explain means a departure is always explained.")
        self.practice_applied_count, self.practice_assessed_count, self.practice_total_count = applied, assessed, in_scope
        self.practice_application_percent = round(100.0 * applied / in_scope, 2) if in_scope else 0.0
