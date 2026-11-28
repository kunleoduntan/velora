from velora import Document
from velora_governance.runtime import host as frappe

class GovernanceExceptionConfiguration(Document):
    def validate(self):
        from velora_governance.governance.services.governance_exception_configuration import validate_exception_configuration
        values = {k: getattr(self, k, None) for k in ("low_days", "medium_days", "high_days", "critical_days", "low_score", "medium_score", "high_score", "critical_score")}
        values["routes"] = {"Low": self.route_low, "Medium": self.route_medium, "High": self.route_high, "Critical": self.route_critical}
        values["evidence_required"] = self.evidence_required
        result = validate_exception_configuration(values)
        if not result["valid"]:
            message = "; ".join(result["errors"])
            if frappe: frappe.throw(message)
            raise ValueError(message)
