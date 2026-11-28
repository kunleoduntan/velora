from velora import Document, throw


class EmissionFactor(Document):
    def validate(self):
        if float(self.kgco2e_per_unit or 0) < 0 or float(self.biogenic_co2_kg_per_unit or 0) < 0:
            throw("Emission Factor cannot be negative.")
        gases = [g.gas.strip().upper() for g in (self.get("gases") or []) if g.gas]
        if len(gases) != len(set(gases)):
            throw("Each gas can appear only once in a factor.")
        if gases and float(self.kgco2e_per_unit or 0):
            throw("Use either a combined kg CO2e factor or gas-by-gas factors, not both: the gas rows would be counted twice.")
