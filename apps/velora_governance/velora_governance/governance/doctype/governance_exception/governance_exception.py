"""Governance Exception document validation."""
from velora import Document
from velora_governance.runtime import host as frappe


class GovernanceException(Document):
    def validate(self):
        if self.risk_score is not None and not 0 <= int(self.risk_score) <= 100:
            if frappe:
                frappe.throw("Risk score must be between 0 and 100")
            raise ValueError("Risk score must be between 0 and 100")
        if self.status in ("Resolved", "Closed") and not (self.resolution_evidence or "").strip():
            if frappe:
                frappe.throw("Resolution evidence is required before resolving or closing an exception")
            raise ValueError("Resolution evidence is required before resolving or closing an exception")
