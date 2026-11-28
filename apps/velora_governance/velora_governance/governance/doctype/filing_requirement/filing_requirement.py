from velora import Document, get_list, throw

class FilingRequirement(Document):
    def validate(self):
        if self.default_lead_days is not None and int(self.default_lead_days)<0:
            throw("Default Lead Days cannot be negative.")
        if self.authority and self.jurisdiction:
            rows=get_list("Regulatory Authority",filters=[["name","=",self.authority]],fields=["country"],limit=1)
            if rows and rows[0].get("country") and rows[0].get("country") != self.jurisdiction:
                throw("Filing Requirement jurisdiction must match the Regulatory Authority country.")
