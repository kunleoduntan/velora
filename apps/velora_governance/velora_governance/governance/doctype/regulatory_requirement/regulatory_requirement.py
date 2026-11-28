from velora import Document, get_list, throw

class RegulatoryRequirement(Document):
    def validate(self):
        if self.authority and self.jurisdiction:
            rows=get_list("Regulatory Authority",filters=[["name","=",self.authority]],fields=["country"],limit=1)
            if rows and rows[0].get("country") and rows[0].get("country") != self.jurisdiction:
                throw("Regulatory Requirement jurisdiction must match the Regulatory Authority country.")
