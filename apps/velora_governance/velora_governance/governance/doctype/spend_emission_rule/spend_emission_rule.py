from velora import Document, get_list, throw


class SpendEmissionRule(Document):
    def validate(self):
        if not any((self.match_account, self.match_item_group, self.match_item, self.match_supplier)):
            throw("A rule needs at least one match (account, item group, item or supplier). A rule that matches everything would classify all spend.")
        if (self.spend_per_factor_unit or 0) <= 0:
            throw("Books currency per factor unit must be greater than zero.")
        if self.treatment == "Exclude from inventory":
            if not (self.exclusion_reason or "").strip():
                throw("State why this spend is excluded (for example: tax, payroll, financing, or covered by another source). Excluded spend stays visible in the coverage figure.")
            self.emission_source = None; self.emission_factor = None
            return
        if not self.emission_source or not self.emission_factor:
            throw("Choose the Emission Source and the spend-based Emission Factor.")
        src = get_list("Emission Source", filters=[["name", "=", self.emission_source]], fields=["governance_entity", "unit", "scope"], limit=1, ignore_permissions=True)
        fac = get_list("Emission Factor", filters=[["name", "=", self.emission_factor]], fields=["unit"], limit=1, ignore_permissions=True)
        if not src or not fac:
            throw("Emission Source and Emission Factor must be valid records.")
        if src[0]["governance_entity"] != self.governance_entity:
            throw("The Emission Source belongs to a different governance entity.")
        if src[0]["unit"] != fac[0]["unit"]:
            throw("The Emission Source unit and the Emission Factor unit differ. A spend-based factor and its source must both use the currency unit.")
