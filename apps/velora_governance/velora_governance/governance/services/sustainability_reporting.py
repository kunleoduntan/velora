"""Deterministic sustainability disclosure readiness and content helpers."""
from __future__ import annotations

def readiness(*, required_data_points=0, complete_data_points=0, evidence_required=False, evidence_complete=False, narrative_required=False, narrative_complete=False):
    checks=[]
    if required_data_points > 0: checks.append(max(0,min(100,complete_data_points/required_data_points*100)))
    if evidence_required: checks.append(100 if evidence_complete else 0)
    if narrative_required: checks.append(100 if narrative_complete else 0)
    return round(sum(checks)/len(checks),2) if checks else 100.0

def status_for_readiness(percent, *, applicable=True):
    if not applicable: return "Not Applicable"
    if percent >= 100: return "Ready"
    if percent <= 0: return "Not Started"
    return "In Progress"

def assess_disclosures(disclosures, datapoints_by_disclosure=None, evidence_by_disclosure=None, narratives_by_disclosure=None):
    """Assess disclosure rows from supplied normalized records; no DB writes."""
    datapoints_by_disclosure=datapoints_by_disclosure or {}; evidence_by_disclosure=evidence_by_disclosure or {}; narratives_by_disclosure=narratives_by_disclosure or {}
    results=[]
    for row in disclosures:
        key=row.get("disclosure") or row.get("name")
        applicable=bool(row.get("applicable",True))
        required=int(row.get("data_points_required",0) or 0); complete=int(datapoints_by_disclosure.get(key,row.get("data_points_complete",0)) or 0)
        evidence_required=bool(row.get("evidence_required",False)); evidence_complete=bool(evidence_by_disclosure.get(key,row.get("evidence_complete",False)))
        narrative_required=bool(row.get("narrative_required",False)); narrative_complete=bool(narratives_by_disclosure.get(key,row.get("narrative_complete",False)))
        pct=readiness(required_data_points=required,complete_data_points=complete,evidence_required=evidence_required,evidence_complete=evidence_complete,narrative_required=narrative_required,narrative_complete=narrative_complete)
        status=status_for_readiness(pct,applicable=applicable)
        results.append({"disclosure":key,"applicable":applicable,"data_points_required":required,"complete_data_points":complete,"evidence_required":evidence_required,"evidence_complete":evidence_complete,"narrative_required":narrative_required,"narrative_complete":narrative_complete,"readiness_percent":pct,"assessment_status":status,"gap_summary":_gap(required,complete,evidence_required,evidence_complete,narrative_required,narrative_complete,applicable)})
    return results

def _gap(required,complete,evidence_required,evidence_complete,narrative_required,narrative_complete,applicable):
    if not applicable:return "Not applicable for this reporting entity/period."
    gaps=[]
    if required>complete:gaps.append(f"Data points missing: {required-complete}")
    if evidence_required and not evidence_complete:gaps.append("Evidence required")
    if narrative_required and not narrative_complete:gaps.append("Disclosure narrative required")
    return "; ".join(gaps) if gaps else "No outstanding readiness gaps."

def generate_content_blocks(*, entity_name, period_name, framework_name, disclosures, metrics=None, targets=None, risks=None, material_topics=None, ghg_summary=None):
    """Produce draft blocks from supplied data; outputs must be reviewed before publication."""
    blocks=[]; seq=10
    blocks.append({"sequence":seq,"block_type":"Executive Summary","title":f"Sustainability overview - {period_name}","generated_content":f"Draft sustainability reporting overview for {entity_name}, reporting period {period_name}, under {framework_name}. This content is generated from configured source records and requires management review.","content_status":"Generated"});seq+=10
    for d in disclosures or []:
        blocks.append({"sequence":seq,"block_type":"Disclosure Narrative","framework":framework_name,"disclosure":d.get("disclosure"),"title":d.get("disclosure_title") or d.get("disclosure_code") or "Disclosure","generated_content":d.get("narrative") or d.get("summary") or "Draft disclosure: complete the narrative using validated source data, evidence and management-approved explanations.","content_status":"Generated"});seq+=10
    for kind, title, data in [("Metric Summary","Metrics",metrics),("Target Progress","Targets",targets),("Risk and Opportunity","Risks and opportunities",risks),("Materiality Summary","Material topics",material_topics),("GHG Summary","GHG emissions",ghg_summary)]:
        if data:
            blocks.append({"sequence":seq,"block_type":kind,"title":title,"generated_content":_summarize(data),"content_status":"Generated"});seq+=10
    return blocks

def _summarize(data):
    if isinstance(data,str): return data
    if isinstance(data,dict): return "\n".join(f"{k}: {v}" for k,v in data.items())
    if isinstance(data,(list,tuple)): return "\n".join(_summarize(x) for x in data)
    return str(data)


def orchestrate_reporting_period(*, entity_name, period_name, frameworks, disclosures, datapoints, evidence, narratives=None, metrics=None, targets=None, risks=None, material_topics=None, ghg_summary=None):
    """Build a deterministic reporting-period assessment and draft report package from normalized records.

    Input records are expected to be permission-checked by the calling application layer.
    This function is intentionally side-effect-free so the framework can persist results
    transactionally and enforce its workflow/approval engine.
    """
    narratives = narratives or {}
    dp_map = {}; evidence_map = {}; narrative_map = {}
    disclosure_keys = {d.get("disclosure") or d.get("name") for d in disclosures}
    for row in datapoints or []:
        key = row.get("disclosure") or row.get("disclosure_code") or row.get("disclosure_name")
        if key in disclosure_keys and row.get("status", "Complete") in ("Complete", "Verified", "Approved"):
            dp_map[key] = dp_map.get(key, 0) + 1
    for row in evidence or []:
        key = row.get("disclosure") or row.get("disclosure_code") or row.get("disclosure_name")
        if key in disclosure_keys and row.get("evidence_status", row.get("status", "Submitted")) in ("Submitted", "Verified", "Approved"):
            evidence_map[key] = True
    for key, value in narratives.items():
        narrative_map[key] = bool(str(value or "").strip())
    assessment = assess_disclosures(disclosures, dp_map, evidence_map, narrative_map)
    applicable = [r for r in assessment if r["applicable"]]
    readiness_pct = round(sum(r["readiness_percent"] for r in applicable) / len(applicable), 2) if applicable else 100.0
    ready_count = sum(1 for r in applicable if r["assessment_status"] == "Ready")
    not_applicable = sum(1 for r in assessment if not r["applicable"])
    gaps = [r for r in assessment if r["applicable"] and r["assessment_status"] != "Ready"]
    report_blocks = generate_content_blocks(entity_name=entity_name, period_name=period_name, framework_name=", ".join(frameworks or []), disclosures=disclosures, metrics=metrics, targets=targets, risks=risks, material_topics=material_topics, ghg_summary=ghg_summary)
    return {"reporting_period": period_name, "frameworks": list(frameworks or []), "disclosure_assessments": assessment, "summary": {"total_disclosures": len(assessment), "applicable_disclosures": len(applicable), "not_applicable": not_applicable, "ready": ready_count, "not_ready": len(gaps), "readiness_percent": readiness_pct, "missing_disclosures": [r["disclosure"] for r in gaps]}, "content_blocks": report_blocks, "report_status": "In Progress" if gaps else "Ready for Review"}

def build_disclosure_data_requirements(disclosure_rows):
    """Return normalized per-disclosure requirements for task creation and mapping."""
    requirements = []
    for row in disclosure_rows or []:
        key = row.get("disclosure") or row.get("name")
        requirements.append({"disclosure": key, "applicable": bool(row.get("applicable", True)), "required_data_points": max(0, int(row.get("data_points_required", 0) or 0)), "evidence_required": bool(row.get("evidence_required", False)), "narrative_required": bool(row.get("narrative_required", False)), "data_collection_needed": bool(row.get("applicable", True)) and int(row.get("data_points_required", 0) or 0) > 0})
    return requirements


def create_collection_task_specs(*, reporting_period, disclosure_requirements, existing_task_keys=None):
    """Create idempotent task specifications for applicable disclosure requirements.

    The persistence adapter must use task_key as a uniqueness/idempotency key and
    perform permission-aware writes in a transaction.
    """
    existing_task_keys = set(existing_task_keys or [])
    specs = []
    for requirement in disclosure_requirements or []:
        disclosure = requirement.get("disclosure") or requirement.get("name")
        if not disclosure or not requirement.get("applicable", True):
            continue
        req_count = max(0, int(requirement.get("required_data_points", requirement.get("data_points_required", 0)) or 0))
        if req_count:
            key = f"{reporting_period}::{disclosure}::data"
            if key not in existing_task_keys:
                specs.append({"task_key": key, "reporting_period": reporting_period, "disclosure": disclosure,
                             "task_type": "Data Collection", "required_items": req_count,
                             "task_title": f"Collect data for {disclosure}", "task_status": "Open"})
        if requirement.get("evidence_required"):
            key = f"{reporting_period}::{disclosure}::evidence"
            if key not in existing_task_keys:
                specs.append({"task_key": key, "reporting_period": reporting_period, "disclosure": disclosure,
                             "task_type": "Evidence Collection", "required_items": 1,
                             "task_title": f"Provide evidence for {disclosure}", "task_status": "Open"})
        if requirement.get("narrative_required"):
            key = f"{reporting_period}::{disclosure}::narrative"
            if key not in existing_task_keys:
                specs.append({"task_key": key, "reporting_period": reporting_period, "disclosure": disclosure,
                             "task_type": "Narrative Preparation", "required_items": 1,
                             "task_title": f"Prepare narrative for {disclosure}", "task_status": "Open"})
    return specs


def map_records_to_disclosures(*, disclosure_rows, datapoints, evidence, narratives=None):
    """Normalize source record matching to disclosure assessments without database access."""
    narratives = narratives or {}
    by_key = {row.get("disclosure") or row.get("name"): row for row in disclosure_rows or []}
    normalized = {key: {"data_points": [], "evidence": [], "narrative": narratives.get(key, "")}
                  for key in by_key}
    for row in datapoints or []:
        key = row.get("disclosure") or row.get("disclosure_code") or row.get("disclosure_name")
        if key in normalized:
            normalized[key]["data_points"].append(row)
    for row in evidence or []:
        key = row.get("disclosure") or row.get("disclosure_code") or row.get("disclosure_name")
        if key in normalized:
            normalized[key]["evidence"].append(row)
    results = []
    for key, disclosure in by_key.items():
        matched_dp = normalized[key]["data_points"]
        completed_dp = [r for r in matched_dp if r.get("verification_status", r.get("status", "Complete")) in ("Complete", "Reviewed", "Verified", "Approved")]
        matched_ev = normalized[key]["evidence"]
        completed_ev = [r for r in matched_ev if (bool(r.get("verified")) if "verified" in r else r.get("evidence_status", r.get("status", "Submitted")) in ("Submitted", "Verified", "Approved"))]
        narrative = str(normalized[key]["narrative"] or "").strip()
        results.append({"disclosure": key, "applicable": bool(disclosure.get("applicable", True)),
                       "matched_data_point_names": [r.get("name") or r.get("data_point") or r.get("metric") for r in matched_dp],
                       "complete_data_points": len(completed_dp), "matched_evidence_names": [r.get("name") or r.get("evidence") for r in matched_ev],
                       "evidence_complete": bool(completed_ev), "narrative_complete": bool(narrative),
                       "narrative": narrative, "data_point_records": matched_dp, "evidence_records": matched_ev})
    return results


def assemble_report_package(*, entity_name, period_name, frameworks, disclosure_rows, datapoints, evidence,
                            narratives=None, metrics=None, targets=None, risks=None, material_topics=None, ghg_summary=None):
    """Return a persistence-ready report package with assessments and content blocks."""
    mapped = map_records_to_disclosures(disclosure_rows=disclosure_rows, datapoints=datapoints,
                                       evidence=evidence, narratives=narratives)
    dp_counts = {r["disclosure"]: r["complete_data_points"] for r in mapped}
    ev_status = {r["disclosure"]: r["evidence_complete"] for r in mapped}
    narr_status = {r["disclosure"]: r["narrative_complete"] for r in mapped}
    assessment = assess_disclosures(disclosure_rows, dp_counts, ev_status, narr_status)
    assessment_lookup = {r["disclosure"]: r for r in assessment}
    enriched = []
    for mapping in mapped:
        assessment_row = assessment_lookup[mapping["disclosure"]]
        enriched.append({**mapping, **assessment_row})
    applicable = [a for a in assessment if a["applicable"]]
    ready = sum(1 for a in applicable if a["assessment_status"] == "Ready")
    missing = [a["disclosure"] for a in applicable if a["assessment_status"] != "Ready"]
    percent = round(sum(a["readiness_percent"] for a in applicable) / len(applicable), 2) if applicable else 100.0
    blocks = generate_content_blocks(entity_name=entity_name, period_name=period_name,
                                    framework_name=", ".join(frameworks or []), disclosures=enriched,
                                    metrics=metrics, targets=targets, risks=risks,
                                    material_topics=material_topics, ghg_summary=ghg_summary)
    return {"reporting_period": period_name, "frameworks": list(frameworks or []),
            "disclosure_assessments": enriched,
            "summary": {"total_disclosures": len(assessment), "applicable_disclosures": len(applicable),
                       "not_applicable": sum(1 for a in assessment if not a["applicable"]),
                       "ready": ready, "not_ready": len(missing), "readiness_percent": percent,
                       "missing_disclosures": missing},
            "content_blocks": blocks, "report_status": "In Progress" if missing else "Ready for Review"}
