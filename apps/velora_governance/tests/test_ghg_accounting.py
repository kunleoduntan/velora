"""GHG accounting: gas-by-gas conversion, GWP sets, Scope 2 dual reporting, Scope 3 categories, biogenic CO2, inventory roll-up."""
from datetime import date
from decimal import Decimal

import pytest
import velora
from velora import get_list, new_doc
from velora.permissions import Session, session_as

from velora_governance.governance.services import ghg_accounting as acct

ADMIN = Session("Administrator", frozenset({"System Manager"}))
APPS = ["velora_notify", "velora_erp", "velora_projectone", "velora_admin", "velora_governance"]
AR5 = acct.GWP_SETS["IPCC AR5 (100-year)"]; AR6 = acct.GWP_SETS["IPCC AR6 (100-year)"]


def test_combined_factor_and_gas_by_gas_agree_when_built_from_the_same_gases():
    gases = [{"gas": "CO2", "kg_per_unit": 2.68}, {"gas": "CH4", "kg_per_unit": 0.0003}, {"gas": "N2O", "kg_per_unit": 0.00002}]
    r = acct.convert(100, {"gases": gases}, AR5)
    expected = 100 * (2.68 + 0.0003 * 28 + 0.00002 * 265)
    assert abs(float(r["kgco2e"]) - expected) < 1e-4
    assert [g["gas"] for g in r["gases"]] == ["CO2", "CH4", "N2O"] and r["gases"][1]["gwp"] == 28
    assert acct.convert(10, {"kgco2e_per_unit": 2.5}, None)["kgco2e"] == Decimal("25.000000")


def test_the_gwp_edition_changes_the_answer_and_a_missing_gwp_is_an_error_not_zero():
    gases = [{"gas": "CH4", "kg_per_unit": 1}]
    assert acct.convert(1, {"gases": gases}, AR5)["kgco2e"] == Decimal("28.000000")
    assert acct.convert(1, {"gases": gases}, AR6)["kgco2e"] == Decimal("29.800000")
    with pytest.raises(ValueError, match="no value for CH4"):
        acct.convert(1, {"gases": gases}, {"N2O": 265})
    with pytest.raises(ValueError, match="negative"):
        acct.convert(-1, {"kgco2e_per_unit": 1})


def test_biogenic_co2_is_reported_apart_and_never_added_to_the_total():
    r = acct.convert(1000, {"kgco2e_per_unit": 0.5, "biogenic_co2_kg_per_unit": 1.8})
    assert r["kgco2e"] == Decimal("500.000000") and r["biogenic_co2_kg"] == Decimal("1800.000000")


def test_inventory_reports_scope2_both_ways_scope3_by_category_and_intensity():
    calcs = [{"scope": "Scope 1", "kgco2e": 10000}, {"scope": "Scope 2", "scope2_method": "Location-based", "kgco2e": 5000},
             {"scope": "Scope 2", "scope2_method": "Market-based", "kgco2e": 2000},
             {"scope": "Scope 3", "scope3_category": "6. Business travel", "kgco2e": 3000}, {"scope": "Scope 3", "scope3_category": "6. Business travel", "kgco2e": 1000},
             {"scope": "Scope 3", "scope3_category": "5. Waste generated in operations", "kgco2e": 500, "biogenic_co2_kg": 40}]
    s = acct.summarise(calcs, base_year_tco2e=20, denominators={"per employee": 10})
    assert (s["scope1_tco2e"], s["scope2_location_tco2e"], s["scope2_market_tco2e"], s["scope3_tco2e"]) == (Decimal("10"), Decimal("5"), Decimal("2"), Decimal("4.5"))
    assert s["scope3_by_category"]["6. Business travel"] == Decimal("4") and s["biogenic_co2_tco2"] == Decimal("0.04")
    assert s["total_location_based_tco2e"] == Decimal("19.5") and s["total_market_based_tco2e"] == Decimal("16.5")      # market-based swaps only Scope 2
    assert s["intensity"]["per employee"] == Decimal("1.95") and s["change_vs_base_year_percent"] == Decimal("-2.5")
    assert not s["warnings"]


def test_the_inventory_warns_instead_of_hiding_missing_method_or_category():
    s = acct.summarise([{"scope": "Scope 2", "kgco2e": 1000}, {"scope": "Scope 3", "kgco2e": 1000}, {"kgco2e": 5}])
    assert len(s["warnings"]) >= 3 and s["scope3_by_category"] == {"Uncategorised": Decimal("1")}


@pytest.fixture
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'g.db'}", apps=APPS, developer_mode=True)
    velora.init(); velora.migrate()
    from velora_governance.setup import after_install
    with session_as(ADMIN):
        after_install()
        yield


def _cat():
    return get_list("Emission Source Category", fields=["name"], limit=1)[0]["name"]


def _entity():
    t = get_list("Governance Entity Type", fields=["name"], limit=1)[0]["name"]
    return new_doc("Governance Entity", entity_name="Acme Ltd", legal_name="Acme Limited", country="Nigeria", entity_type=t).insert()


def test_seeded_gwp_sets_and_a_calculation_end_to_end(site):
    names = {r["set_name"] for r in get_list("GWP Set", fields=["set_name"], limit=10)}
    assert {"IPCC AR5 (100-year)", "IPCC AR6 (100-year)"} <= names
    ar6 = next(r["name"] for r in get_list("GWP Set", filters=[["set_name", "=", "IPCC AR6 (100-year)"]], fields=["name"], limit=1))
    unit = get_list("Sustainability Unit", filters=[["unit_name", "=", "litre"]], fields=["name"], limit=1)[0]["name"]
    entity = _entity()
    src = new_doc("Emission Source", governance_entity=entity.name, scope="Scope 1", source_name="Generator diesel", source_category=_cat(), unit=unit, active=1).insert()
    fac = new_doc("Emission Factor", factor_name="Diesel (gas by gas)", source="Own", unit=unit, kgco2e_per_unit=0, factor_year=2026, active=1,
                  gases=[{"gas": "CO2", "kg_per_unit": 2.51}, {"gas": "CH4", "kg_per_unit": 0.0001}, {"gas": "N2O", "kg_per_unit": 0.00002}]).insert()
    calc = new_doc("GHG Calculation", governance_entity=entity.name, emission_source=src.name, reporting_period="FY2026", activity_quantity=1000, unit=unit, emission_factor=fac.name, gwp_set=ar6).insert()
    assert calc.scope == "Scope 1" and len(calc.gases) == 3
    assert abs(calc.emissions_kgco2e - 1000 * (2.51 + 0.0001 * 29.8 + 0.00002 * 273)) < 1e-3
    # a gas-by-gas factor with no GWP set is refused
    with pytest.raises(Exception, match="GWP Set"):
        new_doc("GHG Calculation", governance_entity=entity.name, emission_source=src.name, reporting_period="FY2026", activity_quantity=1, unit=unit, emission_factor=fac.name).insert()
    # combined AND gas rows would double count
    with pytest.raises(Exception, match="not both"):
        new_doc("Emission Factor", factor_name="bad", unit=unit, kgco2e_per_unit=2, gases=[{"gas": "CO2", "kg_per_unit": 1}]).insert()


def test_scope2_needs_a_method_scope3_needs_a_category_and_the_inventory_rolls_up(site):
    unit = get_list("Sustainability Unit", filters=[["unit_name", "=", "kWh"]], fields=["name"], limit=1)[0]["name"]
    entity = _entity()
    fac = new_doc("Emission Factor", factor_name="Grid", unit=unit, kgco2e_per_unit=0.43, factor_year=2026, active=1, scope2_method="Location-based").insert()
    mfac = new_doc("Emission Factor", factor_name="Supplier", unit=unit, kgco2e_per_unit=0.1, factor_year=2026, active=1, scope2_method="Market-based").insert()
    s2 = new_doc("Emission Source", governance_entity=entity.name, scope="Scope 2", source_name="Grid power", source_category=_cat(), unit=unit, active=1).insert()
    def calc(source, factor, **kw):
        return new_doc("GHG Calculation", governance_entity=entity.name, emission_source=source.name, reporting_period="FY2026", activity_quantity=10000, unit=unit, emission_factor=factor.name, **kw)
    with pytest.raises(Exception, match="Location-based|location-based"):
        calc(s2, mfac, scope2_method="Location-based").insert()           # factor says market-based
    loc = calc(s2, fac).insert(); mkt = calc(s2, mfac).insert()
    assert (loc.scope2_method, mkt.scope2_method) == ("Location-based", "Market-based")
    s3 = new_doc("Emission Source", governance_entity=entity.name, scope="Scope 3", source_name="Flights", source_category=_cat(), unit=unit, active=1).insert()
    with pytest.raises(Exception, match="Scope 3 category"):
        calc(s3, fac).insert()
    new_doc("GHG Inventory Setting", governance_entity=entity.name, consolidation_approach="Operational control", base_year=2024, base_year_emissions_tco2e=10).insert()
    inv = acct.inventory_for(entity.name, "FY2026")
    assert inv["scope2_location_tco2e"] == "4.3" or float(inv["scope2_location_tco2e"]) == 4.3
    assert float(inv["scope2_market_tco2e"]) == 1.0 and inv["organisational_boundary"] == "Operational control"
    assert float(inv["change_vs_base_year_percent"]) == pytest.approx(-57.0)


def test_completed_assurance_locks_the_periods_data_until_an_administrator_releases_it(site):
    unit = get_list("Sustainability Unit", filters=[["unit_name", "=", "kWh"]], fields=["name"], limit=1)[0]["name"]
    entity = _entity()
    period = new_doc("Sustainability Reporting Period", governance_entity=entity.name, period_name="FY2026", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), period_type="Annual").insert()
    report = new_doc("Sustainability Report", governance_entity=entity.name, reporting_period="FY2026").insert()
    src = new_doc("Emission Source", governance_entity=entity.name, scope="Scope 1", source_name="Boiler", source_category=_cat(), unit=unit, active=1).insert()
    fac = new_doc("Emission Factor", factor_name="F", unit=unit, kgco2e_per_unit=0.5, factor_year=2026, active=1).insert()
    calc = new_doc("GHG Calculation", governance_entity=entity.name, emission_source=src.name, reporting_period="FY2026", activity_quantity=100, unit=unit, emission_factor=fac.name).insert()
    a = new_doc("Sustainability Assurance", governance_entity=entity.name, report=report.name, provider="Audit Firm", assurance_type="Limited", assurance_status="In Progress").insert()
    # a completed engagement must be fully described
    a.assurance_status = "Completed"; a.assurance_date = date(2027, 3, 1); a.report_reference = "AR-1"
    with pytest.raises(Exception, match="Standard"):
        a.save()
    a.assurance_standard = "ISAE 3000 (Revised)"; a.opinion = "Unmodified"; a.reporting_period = period.name
    a.save()
    calc.reload(); calc.activity_quantity = 999
    with pytest.raises(Exception, match="locked by the completed assurance"):
        calc.save()
    with pytest.raises(Exception, match="locked by the completed assurance"):
        new_doc("GHG Calculation", governance_entity=entity.name, emission_source=src.name, reporting_period="FY2026", activity_quantity=1, unit=unit, emission_factor=fac.name).insert()
    with pytest.raises(Exception, match="locked by the completed assurance"):
        calc.delete()
    # releasing needs a reason and the right role
    a.reload(); a.locks_period_data = 0
    with pytest.raises(Exception, match="reason"):
        a.save()
    a.lock_release_reason = "Restating after the auditor found a meter error"
    with session_as(Session("clerk@x.test", frozenset({"Sustainability Officer"}))):
        with pytest.raises(Exception, match="Governance Administrator"):
            a.save(ignore_permissions=True)
    a.save()
    assert a.lock_released_by == "Administrator" and a.lock_released_on
    calc.reload(); calc.activity_quantity = 999; calc.save()
    assert calc.emissions_kgco2e == pytest.approx(499.5)
