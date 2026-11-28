from velora import Document, get_doc, get_list, throw
from velora_governance.governance.services import ghg_accounting as acct


def _first(doctype, filters, fields):
    rows = get_list(doctype, filters=filters, fields=fields, limit=1, ignore_permissions=True)
    return rows[0] if rows else None


class GHGCalculation(Document):
    def validate(self):
        from velora_governance.governance.services.assurance_lock import assert_unlocked
        assert_unlocked(self.governance_entity, self.reporting_period, "This GHG Calculation")
        previous = self._stored_period()
        if previous and previous != self.reporting_period:
            assert_unlocked(self.governance_entity, previous, "This GHG Calculation")
        source = _first("Emission Source", [["name", "=", self.emission_source]], ["governance_entity", "unit", "scope", "scope3_category", "scope2_method"])
        factor_row = _first("Emission Factor", [["name", "=", self.emission_factor]], ["unit"])
        if not source or not factor_row:
            throw("Emission Source and Emission Factor must be valid records.")
        if source.get("governance_entity") != self.governance_entity:
            throw("GHG Calculation Entity must match the Emission Source.")
        if source.get("unit") != self.unit or factor_row.get("unit") != self.unit:
            throw("Activity Unit must match both the Emission Source and Emission Factor.")
        factor = get_doc("Emission Factor", self.emission_factor, ignore_permissions=True)
        scope = source.get("scope")
        self.scope = scope
        self.scope3_category = source.get("scope3_category") if scope == "Scope 3" else None
        if scope == "Scope 3" and not self.scope3_category:
            throw("Choose the Scope 3 category on the Emission Source: a Scope 3 figure is not reportable without one.")
        if scope == "Scope 2":
            method = self.scope2_method or factor.get("scope2_method") or source.get("scope2_method")
            if not method:
                throw("Scope 2 needs a method: location-based or market-based. Set it on the Emission Source, Emission Factor or this calculation.")
            if factor.get("scope2_method") and factor.get("scope2_method") != method:
                throw(f"This emission factor is {factor.get('scope2_method').lower()}; the calculation says {method.lower()}.")
            self.scope2_method = method
        else:
            self.scope2_method = None
        gases = [{"gas": g.gas, "kg_per_unit": g.kg_per_unit} for g in (factor.get("gases") or [])]
        gwp = None
        if gases:
            gwp = self._gwp_values()
        try:
            result = acct.convert(self.activity_quantity, {"kgco2e_per_unit": factor.get("kgco2e_per_unit"), "gases": gases,
                                                           "biogenic_co2_kg_per_unit": factor.get("biogenic_co2_kg_per_unit")}, gwp)
        except ValueError as exc:
            throw(str(exc))
        kg = result["kgco2e"]
        self.emissions_kgco2e = float(kg)
        self.emissions_tco2e = float(acct.q(kg / 1000))
        self.biogenic_co2_kg = float(result["biogenic_co2_kg"])
        self.set("gases", [{"gas": r["gas"], "quantity_kg": float(r["quantity_kg"]), "gwp": float(r["gwp"]), "kgco2e": float(r["kgco2e"])} for r in result["gases"]])

    def _gwp_values(self):
        name = self.gwp_set
        if not name:
            setting = _first("GHG Inventory Setting", [["governance_entity", "=", self.governance_entity]], ["default_gwp_set"])
            name = setting.get("default_gwp_set") if setting else None
        if not name:
            throw("Choose a GWP Set (on this calculation or as the entity's default in GHG Inventory Setting): a gas-by-gas factor cannot be converted without one.")
        self.gwp_set = name
        gwp_set = get_doc("GWP Set", name, ignore_permissions=True)
        return {row.gas: row.gwp for row in (gwp_set.get("values") or [])}

    def before_delete(self):
        from velora_governance.governance.services.assurance_lock import assert_unlocked
        assert_unlocked(self.governance_entity, self.reporting_period, "This GHG Calculation")

    def _stored_period(self):
        if self.is_new():
            return None
        rows = get_list("GHG Calculation", filters=[["name", "=", self.name]], fields=["reporting_period"], limit=1, ignore_permissions=True)
        return rows[0].get("reporting_period") if rows else None
