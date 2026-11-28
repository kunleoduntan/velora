"""Sophisticated governance report catalogue and deterministic report calculations.

Data retrieval remains in the permission-aware API layer. This module is pure and
never reaches into the framework runtime.
"""
from collections import Counter
from datetime import date, datetime

REPORTS = {
    "board_register": {"title":"Board Register & Governance Profile", "doctype":"Board", "fields":["name","board_name","governance_entity","board_type","chair","secretary","effective_from","effective_to","board_status","meeting_frequency","minimum_members","maximum_members","quorum_requirement"], "group_by":"board_status", "description":"Board composition, status, governance entity and operating parameters."},
    "meeting_calendar": {"title":"Board & Committee Meeting Calendar", "doctype":"Board Meeting", "fields":["name","meeting_title","governance_entity","board","committee","meeting_type","scheduled_start","scheduled_end","meeting_status","quorum_required","quorum_met","chair","secretary"], "group_by":"meeting_status", "description":"Upcoming and completed meetings, meeting type and quorum status."},
    "meeting_quorum": {"title":"Meeting Quorum & Attendance", "doctype":"Board Meeting", "fields":["name","meeting_title","governance_entity","board","committee","scheduled_start","meeting_status","quorum_required","quorum_met"], "group_by":"quorum_met", "description":"Meeting quorum status and meeting-level attendance controls."},
    "board_actions": {"title":"Board Action Register", "doctype":"Board Action", "fields":["name","action_title","governance_entity","board","committee","meeting","assigned_owner","due_date","priority","action_status","progress_percent","completion_date","evidence_reference"], "group_by":"action_status", "description":"Board action ownership, due dates, completion and evidence."},
    "board_action_aging": {"title":"Board Action Aging & Overdue", "doctype":"Board Action", "fields":["name","action_title","governance_entity","assigned_owner","due_date","priority","action_status","progress_percent","completion_date"], "group_by":"priority", "description":"Open actions grouped by priority, due date and aging."},
    "resolutions": {"title":"Board Resolution & Voting Register", "doctype":"Board Resolution", "fields":["name","resolution_title","governance_entity","board","committee","meeting","resolution_date","resolution_status","voting_status","votes_for","votes_against","abstentions","total_votes","vote_result","implementation_status"], "group_by":"resolution_status", "description":"Resolution status, voting outcomes and implementation progress."},
    "committee_register": {"title":"Board Committee Register", "doctype":"Board Committee", "fields":["name","committee_name","governance_entity","board","committee_type","chair","secretary","effective_from","effective_to","committee_status","quorum_required"], "group_by":"committee_status", "description":"Committee structure, leadership, mandate term and status."},
    "director_terms": {"title":"Director Appointment & Term Tracker", "doctype":"Board Appointment", "fields":["name","governance_entity","board","board_member","appointment_type","director_classification","independence_status","position","appointment_date","term_start_date","term_end_date","appointment_status","resignation_date","retirement_date"], "group_by":"appointment_status", "description":"Director appointment status, independence, term expiry and exits."},
    "obligations": {"title":"Governance Obligations & Compliance Calendar", "doctype":"Governance Obligation", "fields":["name","requirement","governance_entity","obligation_period","due_date","responsible_owner","obligation_status","last_assessed_on","remediation_action"], "group_by":"obligation_status", "description":"Governance obligations, due dates, owners and remediation."},
    "compliance_assessments": {"title":"Compliance Assessment Results", "doctype":"Compliance Assessment", "fields":["name","obligation","governance_entity","assessment_date","assessor","assessment_result","assessment_status","remediation_due_date","remediation_action"], "group_by":"assessment_result", "description":"Assessment outcome, assessor, remediation status and due date."},
    "risk_register": {"title":"Governance Risk Register", "doctype":"Governance Risk", "fields":["name","governance_entity","risk_title","risk_category","inherent_likelihood","inherent_impact","inherent_score","residual_likelihood","residual_impact","residual_score","treatment","treatment_due_date","risk_status","control_owner"], "group_by":"risk_status", "description":"Inherent/residual risk profile, treatment and owners."},
    "control_assurance": {"title":"Control Testing & Assurance", "doctype":"Governance Control", "fields":["name","governance_entity","control_name","risk","control_type","frequency","control_owner","design_effectiveness","operating_effectiveness","last_tested","next_test_date","control_status"], "group_by":"control_status", "description":"Control design and operating effectiveness, testing and next test dates."},
    "policy_reviews": {"title":"Policy Review & Acknowledgement Tracker", "doctype":"Governance Policy", "fields":["name","governance_entity","policy_title","policy_code","version_number","policy_owner","effective_date","next_review_date","policy_status","acknowledgement_required"], "group_by":"policy_status", "description":"Policy lifecycle, review due dates and acknowledgement requirements."},
    "filings": {"title":"Corporate Filing Tracker", "doctype":"Corporate Filing", "fields":["name","governance_entity","filing_requirement","filing_period","due_date","responsible_owner","filing_status","submitted_on","accepted_on","filing_reference"], "group_by":"filing_status", "description":"Filing deadlines, responsible owners, submission and acceptance."},
    "annual_returns": {"title":"Annual Return Status", "doctype":"Annual Return", "fields":["name","governance_entity","reporting_year","due_date","annual_return_status","filed_on","filing_reference","directors_count","shareholders_count","share_capital"], "group_by":"annual_return_status", "description":"Annual return due dates, filing status and company profile details."},
    "conflicts": {"title":"Conflict of Interest Register", "doctype":"Conflict of Interest Declaration", "fields":["name","governance_entity","board_member","board","committee","declaration_date","declaration_period","conflict_category","conflict_type","related_party","declaration_status","reviewed_by","reviewed_on","renewal_date"], "group_by":"declaration_status", "description":"Conflict declarations, review, mitigation and renewal tracking."},
    "related_parties": {"title":"Related Party Interest Register", "doctype":"Related Party Interest", "fields":["name","governance_entity","board_member","related_party_name","relationship","interest_type","effective_date","review_date","interest_status","resolution"], "group_by":"interest_status", "description":"Related party interests, relationship, review and resolution."},
    "exceptions": {"title":"Governance Exception Register & Analysis", "doctype":"Governance Exception", "fields":["name","source_doctype","source_name","exception_type","title","due_date","overdue_days","risk_score","severity","status","assigned_to","routing_status","resolved_on","closed_on"], "group_by":"status", "description":"Exception severity, status, assignment, overdue and resolution."},
    "esg_readiness": {"title":"Sustainability Disclosure Readiness", "doctype":"Sustainability Disclosure Assessment", "fields":["name","governance_entity","reporting_period","disclosure","applicable","assessment_status","readiness_percent","data_points_required","data_points_complete","evidence_required","evidence_complete","narrative_required","narrative_complete","disclosure_owner","due_date","gap_summary"], "group_by":"assessment_status", "description":"Disclosure applicability, readiness, data/evidence/narrative completeness and gaps."},
    "esg_tasks": {"title":"Sustainability Data Collection Workload", "doctype":"Sustainability Data Collection Task", "fields":["name","governance_entity","metric","reporting_period","disclosure","task_type","due_date","responsible_owner","task_status","data_point"], "group_by":"task_status", "description":"Data collection tasks, workload, ownership and progress."},
    "esg_targets": {"title":"Sustainability Targets & Progress", "doctype":"Sustainability Target", "fields":["name","governance_entity","metric","target_title","baseline_value","baseline_year","target_value","target_year","target_direction","unit","current_value","progress_percent","target_status","target_owner","initiative"], "group_by":"target_status", "description":"Baseline, target, current performance and progress toward ESG goals."},
    "ghg_emissions": {"title":"GHG Emissions Inventory", "doctype":"GHG Calculation", "fields":["name","governance_entity","emission_source","reporting_period","activity_quantity","unit","emission_factor","emissions_kgco2e","emissions_tco2e","methodology","data_quality"], "group_by":"reporting_period", "description":"Emissions by source and period, quantity, factor and data quality."},
    "materiality": {"title":"Materiality Assessment Status", "doctype":"Materiality Assessment", "fields":["name","governance_entity","reporting_period","methodology","assessment_status","impact_threshold","financial_threshold","completed_on","overall_summary"], "group_by":"assessment_status", "description":"Materiality assessment completion and configured thresholds."},
    "sustainability_reports": {"title":"Sustainability Report Lifecycle", "doctype":"Sustainability Report", "fields":["name","governance_entity","reporting_period","report_status","report_owner","prepared_date","published_date","readiness_percent","missing_sections","assurance","current_revision","finalized_at","published_at"], "group_by":"report_status", "description":"Report readiness, status, publication, assurance and revision."},
}


# Safe date fields available to range filtering for each report.
REPORT_DATE_FIELDS = {
    "meeting_calendar": ["scheduled_start", "scheduled_end"],
    "meeting_quorum": ["scheduled_start"],
    "board_actions": ["due_date", "completion_date"],
    "board_action_aging": ["due_date", "completion_date"],
    "resolutions": ["resolution_date"],
    "director_terms": ["appointment_date", "term_start_date", "term_end_date", "resignation_date", "retirement_date"],
    "obligations": ["due_date", "last_assessed_on"],
    "compliance_assessments": ["assessment_date", "remediation_due_date"],
    "control_assurance": ["last_tested", "next_test_date"],
    "policy_reviews": ["effective_date", "next_review_date"],
    "filings": ["due_date", "submitted_on", "accepted_on"],
    "annual_returns": ["due_date", "filed_on"],
    "conflicts": ["declaration_date", "renewal_date", "reviewed_on"],
    "related_parties": ["effective_date", "review_date"],
    "exceptions": ["due_date", "resolved_on", "closed_on"],
    "esg_readiness": ["due_date"],
    "esg_tasks": ["due_date"],
    "esg_targets": [],
    "ghg_emissions": [],
    "materiality": ["completed_on"],
    "sustainability_reports": ["prepared_date", "published_date", "finalized_at", "published_at"],
}


def report_catalog():
    return [{"report_id": key, **value, "date_fields": REPORT_DATE_FIELDS.get(key, [])} for key, value in REPORTS.items()]


def build_date_filters(report_id, date_field=None, date_from=None, date_to=None):
    """Build safe date range query filters from a report-specific field whitelist."""
    allowed=REPORT_DATE_FIELDS.get(report_id, [])
    if date_field not in allowed or not (date_from or date_to):
        return {}
    def valid_date(value):
        if value in (None, ""):
            return None
        parsed=_as_date(value)
        if not parsed:
            raise ValueError("Date filters must use YYYY-MM-DD format")
        return parsed.isoformat()
    start=valid_date(date_from); end=valid_date(date_to)
    if start and end and start>end:
        raise ValueError("Date range start cannot be after end")
    if start and end:
        return {date_field:["between", [start,end]]}
    if start:
        return {date_field:[">=", start]}
    return {date_field:["<=", end]}


def get_report_definition(report_id):
    if report_id not in REPORTS:
        raise ValueError(f"Unknown Governance report: {report_id}")
    return REPORTS[report_id]


def apply_filters(rows, filters=None):
    filters = filters or {}
    out=[]
    for row in rows or []:
        ok=True
        for field, value in filters.items():
            if value in (None, ""):
                continue
            if isinstance(value, (list, tuple, set)):
                if row.get(field) not in value: ok=False; break
            elif str(row.get(field) or "") != str(value):
                ok=False; break
        if ok: out.append(dict(row))
    return out


def summarize(rows, group_by=None):
    rows=list(rows or [])
    grouped=Counter((str(row.get(group_by) or "Unspecified") for row in rows)) if group_by else Counter()
    summary={"record_count":len(rows),"group_field":group_by,"groups":[{"label":k,"count":v} for k,v in sorted(grouped.items(),key=lambda x:(-x[1],x[0]))]}
    numeric_fields=set()
    for row in rows:
        for k,v in row.items():
            if isinstance(v,(int,float)) and not isinstance(v,bool): numeric_fields.add(k)
    summary["totals"]={k:sum((float(r.get(k)) for r in rows if isinstance(r.get(k),(int,float)) and not isinstance(r.get(k),bool)), 0) for k in sorted(numeric_fields)}
    return summary


def _as_date(value):
    if value in (None, ""): return None
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    try: return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError): return None


def _enrich_deadlines(rows, report_id, today=None):
    today=_as_date(today) or date.today()
    deadline_field=None
    if report_id in {"board_actions","board_action_aging","obligations","filings","annual_returns","policy_reviews","director_terms","control_assurance","meeting_calendar"}:
        deadline_field={"board_actions":"due_date","board_action_aging":"due_date","obligations":"due_date","filings":"due_date","annual_returns":"due_date","policy_reviews":"next_review_date","director_terms":"term_end_date","control_assurance":"next_test_date","meeting_calendar":"scheduled_start"}[report_id]
    if not deadline_field:return rows
    terminal={"Completed","Closed","Resolved","Cancelled","Published","Accepted","Adopted","Filed","Finalized"}
    for row in rows:
        d=_as_date(row.get(deadline_field))
        if not d:continue
        delta=(d-today).days
        status=str(row.get("action_status") or row.get("obligation_status") or row.get("filing_status") or row.get("annual_return_status") or row.get("policy_status") or row.get("appointment_status") or row.get("control_status") or row.get("meeting_status") or "")
        active=status not in terminal
        row["days_to_deadline"]=delta
        row["overdue_days_calculated"]=max(0,-delta) if active else 0
        row["deadline_bucket"]=("Overdue" if delta<0 and active else "Due Today" if delta==0 and active else "Due in 7 Days" if 0<delta<=7 and active else "Due in 30 Days" if 7<delta<=30 and active else "Future" if active else "Completed/Terminal")
    return rows


def _risk_matrix(rows):
    matrix=[[0 for _ in range(5)] for _ in range(5)]
    for row in rows or []:
        likelihood=row.get("residual_likelihood") or row.get("inherent_likelihood")
        impact=row.get("residual_impact") or row.get("inherent_impact")
        try:
            l=int(float(likelihood)); i=int(float(impact))
        except (TypeError, ValueError):
            continue
        if 1 <= l <= 5 and 1 <= i <= 5:
            matrix[l-1][i-1]+=1
    return {"likelihood_labels":["1","2","3","4","5"],"impact_labels":["1","2","3","4","5"],"cells":matrix}


def build_report(report_id, rows, filters=None, today=None):
    definition=get_report_definition(report_id)
    filtered=apply_filters(rows, filters)
    filtered=_enrich_deadlines(filtered,report_id,today)
    columns=list(definition["fields"])
    if any("days_to_deadline" in r for r in filtered):columns.extend(["days_to_deadline","overdue_days_calculated","deadline_bucket"])
    summary=summarize(filtered,definition.get("group_by"))
    summary["overdue_records"]=sum(1 for r in filtered if r.get("overdue_days_calculated",0)>0)
    if report_id in {"board_action_aging","obligations","filings","annual_returns","policy_reviews","director_terms","control_assurance"}:
        buckets=Counter(r.get("deadline_bucket","Unspecified") for r in filtered)
        summary["deadline_buckets"]=[{"label":k,"count":v} for k,v in sorted(buckets.items(),key=lambda x:(-x[1],x[0]))]
    if report_id=="meeting_quorum":
        summary["quorum_met_records"]=sum(1 for r in filtered if str(r.get("quorum_met") or "").lower() in ("1","true","yes","met"))
        summary["quorum_not_met_records"]=sum(1 for r in filtered if str(r.get("quorum_met") or "").lower() in ("0","false","no","not met"))
    if report_id=="esg_readiness":
        vals=[float(r.get("readiness_percent")) for r in filtered if r.get("readiness_percent") not in (None,"")]
        summary["average_readiness_percent"]=round(sum(vals)/len(vals),2) if vals else 0
    if report_id=="risk_register":
        summary["risk_matrix"]=_risk_matrix(filtered)
    if report_id=="ghg_emissions":
        summary["total_emissions_tco2e"]=round(sum(float(r.get("emissions_tco2e") or 0) for r in filtered),6)
        summary["total_emissions_kgco2e"]=round(sum(float(r.get("emissions_kgco2e") or 0) for r in filtered),3)
    return {"report_id":report_id,"title":definition["title"],"description":definition["description"],"doctype":definition["doctype"],"columns":columns,"filters":filters or {},"summary":summary,"rows":filtered}


def compare_report_periods(current_summary, prior_summary):
    """Calculate safe period deltas for report count and numeric summary metrics."""
    current_summary=current_summary or {}; prior_summary=prior_summary or {}
    metrics={"record_count":(current_summary.get("record_count",0),prior_summary.get("record_count",0))}
    for key,value in (current_summary.get("totals") or {}).items():
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            old=(prior_summary.get("totals") or {}).get(key,0)
            if isinstance(old,(int,float)) and not isinstance(old,bool): metrics[key]=(value,old)
    for key,value in current_summary.items():
        if key in {"record_count","totals","groups","group_field","deadline_buckets","risk_matrix"}: continue
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            old=prior_summary.get(key,0)
            if isinstance(old,(int,float)) and not isinstance(old,bool): metrics[key]=(value,old)
    result={}
    for key,(current,prior) in metrics.items():
        delta=current-prior
        pct=(delta/prior*100) if prior else (100.0 if current else 0.0)
        result[key]={"current":current,"prior":prior,"delta":delta,"percent_change":round(pct,2),"comparison":"increase" if delta>0 else "decrease" if delta<0 else "unchanged"}
    current_groups={str(g.get("label")):int(g.get("count",0)) for g in current_summary.get("groups",[])}
    prior_groups={str(g.get("label")):int(g.get("count",0)) for g in prior_summary.get("groups",[])}
    group_deltas={}
    for label in sorted(set(current_groups)|set(prior_groups)):
        current=current_groups.get(label,0); prior=prior_groups.get(label,0); delta=current-prior
        pct=(delta/prior*100) if prior else (100.0 if current else 0.0)
        group_deltas[label]={"current":current,"prior":prior,"delta":delta,"percent_change":round(pct,2),"comparison":"increase" if delta>0 else "decrease" if delta<0 else "unchanged"}
    if group_deltas: result["group_distribution"]=group_deltas
    return result
