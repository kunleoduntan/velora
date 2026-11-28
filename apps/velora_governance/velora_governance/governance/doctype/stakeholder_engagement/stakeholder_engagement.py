from velora import Document, get_list, throw

class StakeholderEngagement(Document):
    def validate(self):
        if self.materiality_assessment:
            rows=get_list("Materiality Assessment",filters=[["name","=",self.materiality_assessment]],fields=["governance_entity"],limit=1)
            if rows and rows[0].get("governance_entity")!=self.governance_entity:
                throw("Stakeholder Engagement and Materiality Assessment must belong to the same Entity.")
