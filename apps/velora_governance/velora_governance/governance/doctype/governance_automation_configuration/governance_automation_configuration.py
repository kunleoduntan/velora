from velora import Document, throw

class GovernanceAutomationConfiguration(Document):
    def validate(self):
        from velora_governance.governance.services.governance_automation_configuration import validate_configuration
        result = validate_configuration(self.as_dict())
        if not result["valid"]:
            throw("Invalid Governance Automation Configuration: " + "; ".join(result["errors"]))
