"""IFRS S1/S2 checklist, double materiality, climate scenario analysis, climate target detail."""
from datetime import date

import pytest
import velora
from velora import get_list, new_doc
from velora.permissions import Session, session_as

from velora_governance.governance.services import issb_checklist as issb
from velora_governance.governance.services.issb_requirements import REQUIREMENTS

ADMIN = Session("Administrator", frozenset({"System Manager"}))
APPS = ["velora_notify", "velora_erp", "velora_projectone", "velora_admin", "velora_governance"]


@pytest.fixture
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'i.db'}", apps=APPS, developer_mode=True)
    velora.init(); velora.migrate()
    from velora_governance.setup import after_install
    with session_as(ADMIN):
        after_install()
        yield


def _entity():
    t = get_list("Governance Entity Type", fields=["name"], limit=1)[0]["name"]
    e = new_doc("Governance Entity", entity_name="Acme Ltd", legal_name="Acme Limited", country="Nigeria", entity_type=t).insert()
    new_doc("Sustainability Reporting Period", governance_entity=e.name, period_name="FY2026", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), period_type="Annual", period_status="Data Collection").insert()
    return e


def _topic(name="Climate Change"):
    return get_list("Sustainability Topic", filters=[["topic_name", "=", name]], fields=["name"], limit=1)[0]["name"]


def test_catalogue_is_unique_complete_for_the_pillars_and_seeded_once(site):
    codes = [r[0] for r in REQUIREMENTS]
    assert len(codes) == len(set(codes)) >= 80
    for std in ("IFRS-S1", "IFRS-S2"):
        pillars = {r[2] for r in REQUIREMENTS if r[1] == std}
        assert {"Governance", "Strategy", "Risk Management", "Metrics and Targets"} <= pillars
    seeded = {d["disclosure_code"] for d in get_list("Sustainability Disclosure", fields=["disclosure_code"], limit=5000)}
    assert set(codes) <= seeded
    assert issb.seed_issb_requirements() == 0                                # idempotent


def test_checklist_reads_evidence_from_the_system_and_flags_unsupported_completion(site):
    e = _entity()
    assert issb.generate_checklist(e.name, "FY2026")["created"] == len(REQUIREMENTS)
    assert issb.generate_checklist(e.name, "FY2026")["created"] == 0
    r = issb.evaluate(e.name, "FY2026")
    assert r["requirements"] == len(REQUIREMENTS) and not r["can_state_compliance"] and r["open_items"] == len(REQUIREMENTS)
    # preparer marks Scope 1 complete, but no GHG data exists -> inconsistency, not readiness
    disc = get_list("Sustainability Disclosure", filters=[["disclosure_code", "=", "S2.29(a)(i)-1"]], fields=["name"], limit=1)[0]["name"]
    a = get_list("Sustainability Disclosure Assessment", filters=[["governance_entity", "=", e.name], ["disclosure", "=", disc]], fields=["name"], limit=1)[0]["name"]
    doc = velora.get_doc("Sustainability Disclosure Assessment", a); doc.narrative_complete = 1; doc.evidence_complete = 1; doc.save()
    r = issb.evaluate(e.name, "FY2026")
    assert any("S2.29(a)(i)-1" in i and "No Scope 1 calculations" in i for i in r["inconsistencies"])
    # now supply the data: the same requirement becomes ready from the inventory
    cat = get_list("Emission Source Category", fields=["name"], limit=1)[0]["name"]
    unit = get_list("Sustainability Unit", filters=[["unit_name", "=", "litre"]], fields=["name"], limit=1)[0]["name"]
    src = new_doc("Emission Source", governance_entity=e.name, scope="Scope 1", source_name="Diesel", source_category=cat, unit=unit, active=1).insert()
    fac = new_doc("Emission Factor", factor_name="D", unit=unit, kgco2e_per_unit=2.6, factor_year=2026, active=1).insert()
    new_doc("GHG Calculation", governance_entity=e.name, emission_source=src.name, reporting_period="FY2026", activity_quantity=100, unit=unit, emission_factor=fac.name).insert()
    r = issb.evaluate(e.name, "FY2026")
    row = next(x for x in r["rows"] if x["code"] == "S2.29(a)(i)-1")
    assert row["readiness_percent"] == 100 and not any("S2.29(a)(i)-1" in i for i in r["inconsistencies"])


def test_double_materiality_scores_either_dimension_and_overrides_need_reasons(site):
    e = _entity(); t1, t2, t3 = _topic("Climate Change"), _topic("Governance"), _topic("Own Workforce")
    def assess(topics, **kw):
        return new_doc("Materiality Assessment", governance_entity=e.name, reporting_period="FY2026", methodology="Double Materiality", assessment_status="Draft", topics=topics, **kw)
    a = assess([
        {"topic": t1, "iro_type": "Impact", "nature": "Actual", "direction": "Negative", "scale": 5, "scope_of_impact": 4, "irremediability": 3},          # severity 4 -> material
        {"topic": t2, "iro_type": "Risk", "financial_magnitude": 5, "financial_likelihood": 4},                                                           # ceil(20/5)=4 -> material (financial)
        {"topic": t3, "iro_type": "Impact", "nature": "Potential", "direction": "Negative", "scale": 5, "scope_of_impact": 5, "irremediability": 5, "impact_likelihood": 1}]).insert()
    rows = {r.topic: r for r in a.topics}
    assert rows[t1].material and rows[t1].material_basis == "Impact" and rows[t1].impact_score == 4
    assert rows[t2].material and rows[t2].material_basis == "Financial" and rows[t2].financial_score == 4
    assert not rows[t3].material                                                                   # severe but very unlikely and not a human-rights case
    a.topics[2].human_rights = 1; a.save()
    assert a.topics[2].material                                                                    # human-rights severity outranks likelihood
    a.topics[2].override = "Not material"
    with pytest.raises(Exception, match="override needs a written reason"):
        a.save()


def test_a_materiality_assessment_cannot_complete_without_sign_off_and_reasons(site):
    e = _entity(); t = _topic("Climate Change"); t2 = _topic("Governance")
    a = new_doc("Materiality Assessment", governance_entity=e.name, reporting_period="FY2026", methodology="Double Materiality", assessment_status="Draft",
                topics=[{"topic": t, "financial_magnitude": 4, "financial_likelihood": 5}, {"topic": t2, "financial_magnitude": 1, "financial_likelihood": 1}]).insert()
    a.assessment_status = "Completed"; a.completed_on = date(2026, 12, 1)
    with pytest.raises(Exception) as exc:
        a.save()
    msg = str(exc.value)
    assert "stakeholder engagement" in msg and "approval" in msg and "rationale for each topic judged not material" in msg
    a.stakeholder_engagement = "Investor and staff survey"; a.approved_by = "Board Sustainability Committee"; a.approved_on = date(2026, 12, 2); a.topics[1].rationale = "Immaterial to enterprise value"
    a.save()
    out = issb.apply_materiality(a.name)
    assert out["updated"] >= 1
    assert {r["materiality_status"] for r in get_list("Disclosure Applicability", fields=["materiality_status"], limit=500)} <= {"Material", "Not Material"}


def test_scenario_analysis_cannot_complete_without_the_s2_22_content(site):
    e = _entity()
    base = dict(governance_entity=e.name, reporting_period="FY2026", analysis_status="In Progress",
                scenarios=[{"scenario_name": "Net zero 2050", "source": "IEA NZE 2023", "scenario_type": "Transition", "aligned_with_latest_agreement": 1},
                           {"scenario_name": "High warming", "source": "IPCC SSP5-8.5", "scenario_type": "Physical"}])
    a = new_doc("Climate Scenario Analysis", **base).insert()
    a.analysis_status = "Completed"
    with pytest.raises(Exception, match="completed Climate Scenario Analysis needs"):
        a.save()
    for f in ("relevance_rationale", "time_horizons", "operations_covered", "policy_assumptions", "macro_assumptions", "regional_assumptions", "energy_assumptions",
              "technology_assumptions", "strategy_implications", "uncertainties"):
        setattr(a, f, "stated")
    a.diverse_range = 1; a.performed_on = date(2026, 10, 1)
    a.save()
    assert issb.system_signals(e.name, "FY2026")["scenario"][0]
    a.set("impacts", [{"scenario_name": "Unknown", "horizon": "Short term", "risk_or_opportunity": "x", "risk_type": "Physical risk", "line_item": "Revenue", "high_amount": 5}])
    with pytest.raises(Exception, match="not in the scenario list"):
        a.save()


def test_a_climate_ghg_target_must_carry_the_s2_33_and_36_detail(site):
    e = _entity()
    metric = get_list("Sustainability Metric", filters=[["metric_code", "=", "ENV-EMISSIONS"]], fields=["name", "default_unit"], limit=1)[0]
    kw = dict(governance_entity=e.name, metric=metric["name"], unit=metric["default_unit"], target_title="Net zero", baseline_value=100, baseline_year=2024, target_value=50, target_year=2035,
              target_direction="Reduce", target_status="On Track", climate_target=1, ghg_target=1)
    with pytest.raises(Exception, match="IFRS S2 paragraphs 33 and 36"):
        new_doc("Sustainability Target", **kw).insert()
    t = new_doc("Sustainability Target", **{**kw, "target_status": "Draft"}).insert()          # draft allowed while detail is gathered
    for f, v in dict(objective="Cut emissions", entity_part_covered="Group", target_basis="Absolute", milestones="2030: -25%", gases_covered="CO2, CH4", scopes_covered="1 and 2",
                     gross_or_net="Net", sectoral_decarbonisation="No").items():
        setattr(t, f, v)
    t.target_status = "On Track"
    with pytest.raises(Exception, match="associated gross target"):
        t.save()
    t.gross_target_if_net = "-40% gross"; t.save()
    assert issb.system_signals(e.name, "FY2026")["targets"][0]
