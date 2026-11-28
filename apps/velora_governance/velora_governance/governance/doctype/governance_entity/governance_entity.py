from velora import Document, get_list, throw

class GovernanceEntity(Document):
    def validate(self):
        if self.parent_entity and self.name and self.parent_entity == self.name:
            throw("An entity cannot be its own parent.")
        seen = set()
        current = self.parent_entity
        while current:
            if current == self.name or current in seen:
                throw("The parent entity hierarchy cannot contain a circular relationship.")
            seen.add(current)
            rows = get_list("Governance Entity", filters=[["name", "=", current]], fields=["parent_entity"], limit=1)
            if not rows:
                break
            current = rows[0].get("parent_entity")
        if self.registration_number and self.country:
            filters = [["registration_number", "=", self.registration_number], ["country", "=", self.country]]
            rows = get_list("Governance Entity", filters=filters, fields=["name"], limit=20)
            if any(row.get("name") != self.name for row in rows):
                throw("Registration Number must be unique within the selected country/jurisdiction.")
