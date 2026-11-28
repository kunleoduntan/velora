"""GHG Protocol accounting: gas-by-gas conversion with a stated GWP set, Scope 2 dual reporting, Scope 3 by category, biogenic CO2 kept apart.

Pure functions (no database) so every number can be tested on its own; the DocTypes call them.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

SCOPE3_CATEGORIES = [
    "1. Purchased goods and services", "2. Capital goods", "3. Fuel- and energy-related activities", "4. Upstream transportation and distribution",
    "5. Waste generated in operations", "6. Business travel", "7. Employee commuting", "8. Upstream leased assets",
    "9. Downstream transportation and distribution", "10. Processing of sold products", "11. Use of sold products", "12. End-of-life treatment of sold products",
    "13. Downstream leased assets", "14. Franchises", "15. Investments",
]
SCOPE2_METHODS = ["Location-based", "Market-based"]
CONSOLIDATION_APPROACHES = ["Operational control", "Financial control", "Equity share"]
# IPCC 100-year global warming potentials (without climate-carbon feedbacks). Seeded as editable data; verify against the edition your regulator requires.
GWP_SETS = {
    "IPCC AR5 (100-year)": {"CO2": 1, "CH4": 28, "N2O": 265, "SF6": 23500, "NF3": 16100, "HFC-134a": 1300, "HFC-32": 677, "HFC-23": 12400},
    "IPCC AR6 (100-year)": {"CO2": 1, "CH4": 29.8, "N2O": 273, "SF6": 25200, "NF3": 17400, "HFC-134a": 1530, "HFC-32": 771, "HFC-23": 14600},
}
_Q = Decimal("0.000001")


def D(value) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


def q(value: Decimal) -> Decimal:
    return value.quantize(_Q, rounding=ROUND_HALF_UP)


def convert(quantity, factor: dict, gwp: dict | None = None) -> dict:
    """Emissions of one activity.

    `factor` is either combined ({"kgco2e_per_unit": x}) or gas-by-gas ({"gases": [{"gas": "CH4", "kg_per_unit": y}, ...]}); a gas-by-gas factor
    needs a GWP for each non-CO2 gas, and a missing one is an error, never a silent zero. `biogenic_co2_kg_per_unit` is reported separately and
    is NOT included in the total, as the GHG Protocol requires.
    """
    qty = D(quantity)
    if qty < 0:
        raise ValueError("Activity Quantity cannot be negative.")
    biogenic = q(qty * D(factor.get("biogenic_co2_kg_per_unit")))
    gases = [g for g in (factor.get("gases") or []) if g.get("gas")]
    if not gases:
        return {"kgco2e": q(qty * D(factor.get("kgco2e_per_unit"))), "gases": [], "biogenic_co2_kg": biogenic}
    rows, total = [], Decimal("0")
    for g in gases:
        name = str(g["gas"]).strip()
        kg = qty * D(g.get("kg_per_unit"))
        if kg < 0 or D(g.get("kg_per_unit")) < 0:
            raise ValueError(f"Emission factor for {name} cannot be negative.")
        if name.upper() == "CO2":
            potential = Decimal("1")
        elif gwp and name in gwp:
            potential = D(gwp[name])
        else:
            raise ValueError(f"The GWP set has no value for {name}. Add it to the GWP Set or choose another set.")
        co2e = q(kg * potential)
        rows.append({"gas": name, "quantity_kg": q(kg), "gwp": potential, "kgco2e": co2e})
        total += co2e
    return {"kgco2e": q(total), "gases": rows, "biogenic_co2_kg": biogenic}


def summarise(calculations: list[dict], *, base_year_tco2e=None, denominators: dict | None = None, scope2_policy: str = "Both") -> dict:
    """Roll calculations up into the inventory a report states.

    Each calculation: scope ("Scope 1/2/3"), kgco2e, optional scope2_method, scope3_category, biogenic_co2_kg, gases.
    Totals are given location-based and market-based, as the GHG Protocol Scope 2 Guidance asks for companies with market instruments.
    """
    warnings: list[str] = []
    s1 = Decimal("0"); s2 = {"Location-based": Decimal("0"), "Market-based": Decimal("0")}; s3: dict[str, Decimal] = {}; biogenic = Decimal("0"); by_gas: dict[str, Decimal] = {}
    for c in calculations:
        kg = D(c.get("kgco2e")); biogenic += D(c.get("biogenic_co2_kg"))
        for g in c.get("gases") or []:
            by_gas[g["gas"]] = by_gas.get(g["gas"], Decimal("0")) + D(g.get("kgco2e"))
        scope = c.get("scope")
        if scope == "Scope 1":
            s1 += kg
        elif scope == "Scope 2":
            method = c.get("scope2_method")
            if method not in s2:
                warnings.append("A Scope 2 calculation has no method (location-based or market-based); it is counted as location-based.")
                method = "Location-based"
            s2[method] += kg
        elif scope == "Scope 3":
            cat = c.get("scope3_category")
            if not cat:
                warnings.append("A Scope 3 calculation has no category; it is listed as 'Uncategorised'.")
                cat = "Uncategorised"
            s3[cat] = s3.get(cat, Decimal("0")) + kg
        else:
            warnings.append("A calculation has no scope and was left out of the totals.")
    s3_total = sum(s3.values(), Decimal("0"))
    t = lambda kg: q(kg / Decimal(1000))
    if scope2_policy == "Both" and s2["Market-based"] == 0 and s2["Location-based"] > 0:
        warnings.append("Only location-based Scope 2 is recorded; the policy is to report both methods.")
    loc_total = s1 + s2["Location-based"] + s3_total
    mkt_total = s1 + (s2["Market-based"] if s2["Market-based"] else s2["Location-based"]) + s3_total
    out = {
        "scope1_tco2e": t(s1), "scope2_location_tco2e": t(s2["Location-based"]), "scope2_market_tco2e": t(s2["Market-based"]),
        "scope3_tco2e": t(s3_total), "scope3_by_category": {k: t(v) for k, v in sorted(s3.items())},
        "total_location_based_tco2e": t(loc_total), "total_market_based_tco2e": t(mkt_total),
        "biogenic_co2_tco2": t(biogenic), "by_gas_tco2e": {k: t(v) for k, v in sorted(by_gas.items())}, "warnings": warnings,
        "market_based_note": "Market-based total uses location-based Scope 2 where no market-based figure was recorded." if s2["Market-based"] == 0 and s2["Location-based"] > 0 else "",
    }
    out["intensity"] = {name: (q(D(out["total_location_based_tco2e"]) / D(value)) if D(value) > 0 else None) for name, value in (denominators or {}).items()}
    if base_year_tco2e and D(base_year_tco2e) > 0:
        out["change_vs_base_year_percent"] = q((D(out["total_location_based_tco2e"]) - D(base_year_tco2e)) / D(base_year_tco2e) * 100)
    return out


def inventory_for(governance_entity: str, reporting_period: str, denominators: dict | None = None) -> dict:
    """The GHG inventory of one entity and reporting period, read from its GHG Calculations (permission-checked by the caller)."""
    from velora import get_list
    rows = get_list("GHG Calculation", filters=[["governance_entity", "=", governance_entity], ["reporting_period", "=", reporting_period]],
                    fields=["name", "scope", "scope2_method", "scope3_category", "emissions_kgco2e", "biogenic_co2_kg", "gwp_set"], limit=100000)
    calcs = [{"scope": r.get("scope"), "scope2_method": r.get("scope2_method"), "scope3_category": r.get("scope3_category"),
              "kgco2e": r.get("emissions_kgco2e"), "biogenic_co2_kg": r.get("biogenic_co2_kg")} for r in rows]
    setting = get_list("GHG Inventory Setting", filters=[["governance_entity", "=", governance_entity]],
                       fields=["consolidation_approach", "base_year", "base_year_emissions_tco2e", "recalculation_threshold_percent", "default_gwp_set"], limit=1)
    setting = setting[0] if setting else {}
    policy = (get_list("Sustainability Settings", fields=["scope2_methodology"], limit=1) or [{}])[0].get("scope2_methodology") or "Both"
    result = summarise(calcs, base_year_tco2e=setting.get("base_year_emissions_tco2e"), denominators=denominators, scope2_policy=policy)
    sets = sorted({r.get("gwp_set") for r in rows if r.get("gwp_set")})
    result.update({"governance_entity": governance_entity, "reporting_period": reporting_period, "calculation_count": len(rows),
                   "organisational_boundary": setting.get("consolidation_approach"), "base_year": setting.get("base_year"),
                   "recalculation_threshold_percent": setting.get("recalculation_threshold_percent"), "gwp_sets_used": sets})
    if not setting:
        result["warnings"].append("No GHG Inventory Setting for this entity: the organisational boundary and base year are not stated.")
    if len(sets) > 1:
        result["warnings"].append("More than one GWP set is used in this period; totals mix editions. Use one set.")
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in result.items()} | {
        "scope3_by_category": {k: str(v) for k, v in result["scope3_by_category"].items()}, "by_gas_tco2e": {k: str(v) for k, v in result["by_gas_tco2e"].items()},
        "intensity": {k: (str(v) if v is not None else None) for k, v in result["intensity"].items()}}
