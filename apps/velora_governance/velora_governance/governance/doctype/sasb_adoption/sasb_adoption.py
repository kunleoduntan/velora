from velora import Document, get_list, throw


class SASBAdoption(Document):
    """An entity's decision to report against one SASB industry standard."""

    def validate(self):
        dup = get_list("SASB Adoption", filters=[["governance_entity", "=", self.governance_entity], ["industry", "=", self.industry], ["name", "!=", self.name or ""]], fields=["name"], limit=1, ignore_permissions=True)
        if dup:
            throw("This entity already has an adoption record for that industry.")
