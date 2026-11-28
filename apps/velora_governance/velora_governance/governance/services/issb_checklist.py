"""IFRS S1 / S2 readiness: seed the requirement catalogue, open one assessment per requirement for a reporting period,
and read readiness from what the system actually holds (GHG inventory, targets, scenario analysis, materiality).

A requirement is only "ready" when the preparer has completed its narrative or data AND, where the system can see the evidence,
the evidence exists. A completed checkbox with no supporting data is reported as an inconsistency, not hidden.
"""
from __future__ import annotations

from velora import get_doc, get_list, new_doc, throw

from velora_governance.governance.services.issb_requirements import REQUIREMENTS
from velora_governance.governance.services.sustainability_reporting import readiness, status_for_readiness

FRAMEWORK_FOR = {"IFRS-S1": "IFRS S1", "IFRS-S2": "IFRS S2"}
TITLE_FOR = {"IFRS-S1": "General Requirements for Sustainability-related Financial Disclosures", "IFRS-S2": "Climate-related Disclosures"}


def seed_issb_requirements() -> int:
    """Idempotent: add the paragraph-level requirements as Sustainability Disclosures."""
    frameworks = {r["framework_name"]: r["name"] for r in get_list("Sustainability Framework", fields=["name", "framework_name"], limit=1000, ignore_permissions=True)}
    standards = {r["standard_code"]: r["name"] for r in get_list("Sustainability Standard", fields=["name", "standard_code"], limit=1000, ignore_permissions=True)}
    types = {r["disclosure_type_name"]: r["name"] for r in get_list("Sustainability Disclosure Type", fields=["name", "disclosure_type_name"], limit=1000, ignore_permissions=True)}
    topics = {r["topic_name"]: r["name"] for r in get_list("Sustainability Topic", fields=["name", "topic_name"], limit=1000, ignore_permissions=True)}
    have = {r["disclosure_code"] for r in get_list("Sustainability Disclosure", fields=["disclosure_code"], limit=10000, ignore_permissions=True)}
    added = 0
    for code, std, pillar, title, text, link, kind in REQUIREMENTS:
        if code in have or std not in standards:
            continue
        new_doc("Sustainability Disclosure", framework=frameworks.get(FRAMEWORK_FOR[std]), standard=standards[std], disclosure_code=code,
                disclosure_title=title, disclosure_type=types.get(pillar) or types.get("Other"),
                topic=topics.get("Climate Change" if std == "IFRS-S2" else "Governance"), required_data=link or "", guidance=text, active=1,
                data_points_required=1 if kind == "quantitative" else 0, evidence_required=1 if kind == "quantitative" else 0, narrative_required=1).insert(ignore_permissions=True)
        added += 1
    return added


def _period_record(entity, period_name):
    rows = get_list("Sustainability Reporting Period", filters=[["governance_entity", "=", entity], ["period_name", "=", period_name]], fields=["name"], limit=1, ignore_permissions=True)
    if not rows:
        throw(f"No Sustainability Reporting Period named '{period_name}' exists for this entity.")
    return rows[0]["name"]


def system_signals(entity, period_name) -> dict:
    """What the system can evidence for each link key. {key: (ok, detail)}"""
    calcs = get_list("GHG Calculation", filters=[["governance_entity", "=", entity], ["reporting_period", "=", period_name]],
                     fields=["scope", "scope2_method", "scope3_category", "emissions_kgco2e"], limit=100000, ignore_permissions=True)
    setting = get_list("GHG Inventory Setting", filters=[["governance_entity", "=", entity]], fields=["consolidation_approach", "default_gwp_set"], limit=1, ignore_permissions=True)
    sig = {}
    for key, scope in (("ghg_scope1", "Scope 1"), ("ghg_scope2", "Scope 2"), ("ghg_scope3", "Scope 3")):
        n = sum(1 for c in calcs if c["scope"] == scope)
        sig[key] = (n > 0, f"{n} calculation(s) for {scope}" if n else f"No {scope} calculations for {period_name}")
    loc = any(c["scope"] == "Scope 2" and c.get("scope2_method") == "Location-based" for c in calcs)
    sig["ghg_location"] = (loc, "Location-based Scope 2 present" if loc else "No location-based Scope 2 calculation")
    cats = {c["scope3_category"] for c in calcs if c["scope"] == "Scope 3" and c.get("scope3_category")}
    sig["ghg_scope3_cats"] = (bool(cats), f"{len(cats)} Scope 3 categor{'y' if len(cats) == 1 else 'ies'} recorded" if cats else "No Scope 3 category recorded")
    ok = bool(setting and setting[0].get("consolidation_approach") and setting[0].get("default_gwp_set"))
    sig["ghg_method"] = (ok, "Boundary and GWP set stated in GHG Inventory Setting" if ok else "Set the organisational boundary and default GWP set in GHG Inventory Setting")
    sig["ghg_boundary"] = (bool(setting and setting[0].get("consolidation_approach")), "Organisational boundary stated" if setting else "No GHG Inventory Setting")
    targets = get_list("Sustainability Target", filters=[["governance_entity", "=", entity], ["climate_target", "=", 1]], fields=["target_status"], limit=1000, ignore_permissions=True)
    live = [t for t in targets if t["target_status"] not in ("Draft", "Cancelled")]
    sig["targets"] = (bool(live), f"{len(live)} climate target(s) with the IFRS S2.33 detail" if live else "No non-draft climate-related targets")
    sc = get_list("Climate Scenario Analysis", filters=[["governance_entity", "=", entity], ["reporting_period", "=", period_name], ["analysis_status", "=", "Completed"]], fields=["name"], limit=1, ignore_permissions=True)
    sig["scenario"] = (bool(sc), "Completed scenario analysis" if sc else "No completed Climate Scenario Analysis for this period")
    mat = get_list("Materiality Assessment", filters=[["governance_entity", "=", entity], ["reporting_period", "=", period_name], ["assessment_status", "=", "Completed"]], fields=["name"], limit=1, ignore_permissions=True)
    sig["materiality"] = (bool(mat), "Completed materiality assessment" if mat else "No completed Materiality Assessment for this period")
    from velora_governance.governance.services import sasb_catalog
    sig["sasb"] = sasb_catalog.signal(entity, period_name)
    return sig


def generate_checklist(entity, period_name) -> dict:
    period = _period_record(entity, period_name)
    seed_issb_requirements()
    disclosures = {r["disclosure_code"]: r for r in get_list("Sustainability Disclosure", fields=["name", "disclosure_code", "data_points_required", "evidence_required", "narrative_required"], limit=10000, ignore_permissions=True)}
    have = {r["disclosure"] for r in get_list("Sustainability Disclosure Assessment", filters=[["governance_entity", "=", entity], ["reporting_period", "=", period]], fields=["disclosure"], limit=10000, ignore_permissions=True)}
    created = 0
    for code, *_ in REQUIREMENTS:
        d = disclosures.get(code)
        if not d or d["name"] in have:
            continue
        new_doc("Sustainability Disclosure Assessment", governance_entity=entity, reporting_period=period, disclosure=d["name"], applicable=1, assessment_status="Not Started",
                data_points_required=d["data_points_required"], data_points_complete=0, evidence_required=d["evidence_required"], narrative_required=d["narrative_required"]).insert(ignore_permissions=True)
        created += 1
    return {"created": created, "total": len(REQUIREMENTS)}


def evaluate(entity, period_name) -> dict:
    period = _period_record(entity, period_name)
    sig = system_signals(entity, period_name)
    by_disclosure = {r["name"]: r for r in get_list("Sustainability Disclosure", fields=["name", "disclosure_code"], limit=10000, ignore_permissions=True)}
    assessments = {by_disclosure[a["disclosure"]]["disclosure_code"]: a for a in get_list(
        "Sustainability Disclosure Assessment", filters=[["governance_entity", "=", entity], ["reporting_period", "=", period]],
        fields=["disclosure", "applicable", "assessment_status", "data_points_required", "data_points_complete", "evidence_required", "evidence_complete",
                "narrative_required", "narrative_complete", "disclosure_owner"], limit=10000, ignore_permissions=True) if a["disclosure"] in by_disclosure}
    rows, inconsistencies, pillars = [], [], {}
    for code, std, pillar, title, text, link, kind in REQUIREMENTS:
        a = assessments.get(code)
        if a is None:
            rows.append({"code": code, "standard": std, "pillar": pillar, "title": title, "status": "No assessment", "readiness_percent": 0, "evidence": sig.get(link, (None, ""))[1] if link else ""})
            pillars.setdefault((std, pillar), []).append(0)
            continue
        ok = sig[link][0] if link in sig else None
        required = int(a["data_points_required"] or 0)
        complete = int(a["data_points_complete"] or 0)
        if ok and required:
            complete = max(complete, required)               # the system holds the data
        pct = readiness(required_data_points=required, complete_data_points=complete, evidence_required=bool(a["evidence_required"]),
                        evidence_complete=bool(a["evidence_complete"]) or bool(ok), narrative_required=bool(a["narrative_required"]), narrative_complete=bool(a["narrative_complete"]))
        applicable = bool(a["applicable"])
        status = status_for_readiness(pct, applicable=applicable)
        if applicable and link in sig and ok is False and (a["narrative_complete"] or a["evidence_complete"] or a["assessment_status"] in ("Ready", "Reviewed")):
            inconsistencies.append(f"{code} {title}: marked complete, but the system finds: {sig[link][1]}.")
            pct = min(pct, 50.0); status = "In Progress"
        rows.append({"code": code, "standard": std, "pillar": pillar, "title": title, "kind": kind, "applicable": applicable, "status": status, "readiness_percent": pct,
                     "evidence": sig[link][1] if link in sig else "", "owner": a.get("disclosure_owner")})
        if applicable:
            pillars.setdefault((std, pillar), []).append(pct)
    summary = [{"standard": s, "pillar": p, "requirements": len(v), "average_readiness": round(sum(v) / len(v), 1), "ready": sum(1 for x in v if x >= 100)} for (s, p), v in pillars.items()]
    open_items = [r for r in rows if r.get("applicable", True) and r["status"] != "Ready"]
    notes = ["IFRS S1 paragraph 72: an unreserved statement of compliance is allowed only when every requirement is met.",
             "IFRS S2 amendments (Dec 2025, effective for annual periods beginning on or after 1 January 2027) change greenhouse gas measurement relief and Category 15 wording; check which version your regulator has adopted."]
    gwp = get_list("GHG Inventory Setting", filters=[["governance_entity", "=", entity]], fields=["default_gwp_set"], limit=1, ignore_permissions=True)
    if gwp and gwp[0].get("default_gwp_set"):
        gs = get_list("GWP Set", filters=[["name", "=", gwp[0]["default_gwp_set"]]], fields=["set_name"], limit=1, ignore_permissions=True)
        if gs and "AR6" not in (gs[0].get("set_name") or ""):
            notes.append("IFRS S2 (B21-B22, as amended) expects 100-year GWP values from the latest IPCC assessment unless a jurisdiction or exchange requires others for the part of the entity it covers. Your default GWP set is not AR6.")
    return {"governance_entity": entity, "reporting_period": period_name, "requirements": len(REQUIREMENTS), "assessed": len(assessments), "rows": rows, "summary": summary,
            "open_items": len(open_items), "inconsistencies": inconsistencies, "notes": notes,
            "can_state_compliance": bool(assessments) and not open_items and not inconsistencies}


def apply_materiality(assessment_name) -> dict:
    """Carry a completed assessment's results into Disclosure Applicability (material / not material) for matching disclosures."""
    ma = get_doc("Materiality Assessment", assessment_name, ignore_permissions=True)
    if ma.assessment_status != "Completed":
        throw("Only a completed, approved Materiality Assessment can drive disclosure applicability.")
    verdict = {}
    for r in ma.topics or []:
        verdict[r.topic] = verdict.get(r.topic, False) or bool(r.material)
    disclosures = get_list("Sustainability Disclosure", fields=["name", "topic"], limit=10000, ignore_permissions=True)
    existing = {(r["disclosure"]): r["name"] for r in get_list("Disclosure Applicability", filters=[["governance_entity", "=", ma.governance_entity], ["reporting_period", "=", ma.reporting_period]],
                fields=["name", "disclosure"], limit=10000, ignore_permissions=True)}
    n = 0
    for d in disclosures:
        if d["topic"] not in verdict:
            continue
        status = "Material" if verdict[d["topic"]] else "Not Material"
        values = dict(governance_entity=ma.governance_entity, disclosure=d["name"], reporting_period=ma.reporting_period, applicable=int(verdict[d["topic"]]), materiality_status=status,
                      rationale=f"From {ma.name}")
        if d["name"] in existing:
            doc = get_doc("Disclosure Applicability", existing[d["name"]], ignore_permissions=True)
            for k, v in values.items():
                doc.set(k, v)
            doc.save(ignore_permissions=True)
        else:
            new_doc("Disclosure Applicability", **values).insert(ignore_permissions=True)
        n += 1
    return {"updated": n, "material_topics": sorted(t for t, v in verdict.items() if v)}
