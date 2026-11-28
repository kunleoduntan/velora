"""Runtime scheduler for exception escalation notifications."""
from datetime import datetime


def run_exception_escalations(*, api=None, now=None, batch_limit=500):
    if api is None:
        from velora_governance.runtime import host as api
    now = now or api.utils.now_datetime()
    config = api.get_single("Governance Exception Configuration")
    intervals = config.escalation_after_hours or "24,72,168"
    raw_targets = config.escalation_targets or "{}"
    if isinstance(raw_targets, str):
        import json
        targets = json.loads(raw_targets or "{}")
    else:
        targets = raw_targets or {}
    from velora_governance.governance.services.governance_exception_escalation import determine_due_stage, escalation_recipients
    from velora_governance.governance.services.governance_exception_activity import append_activity, activity_key
    active = ["Open", "Assigned", "In Progress", "Escalated", "Pending Evidence"]
    rows = api.get_list("Governance Exception", filters={"status": ["in", active]},
        fields=["name", "title", "severity", "status", "assigned_to", "creation"],
        limit_page_length=max(1, min(int(batch_limit), 1000)))
    result = {"checked":len(rows),"escalated":0,"notifications":0,"skipped_unconfigured":0,"invalid_users":0,"errors":[]}
    for row in rows:
        try:
            activity_rows=api.get_list("Governance Exception Activity", filters={"exception":row["name"],"activity_type":"Escalated"},
                fields=["details"],limit_page_length=100)
            stages=[]
            for a in activity_rows:
                try:
                    token=(a.get("details") or "").split("stage=",1)[1].split(";",1)[0]
                    stages.append(int(token))
                except (IndexError,ValueError): pass
            completed=max(stages or [0])
            stage=determine_due_stage(row.get("creation"),now,intervals,completed_stages=completed)
            if stage is None: continue
            recipients=escalation_recipients(targets,stage)
            if not recipients:
                result["skipped_unconfigured"]+=1
                continue
            valid=[]
            for user in recipients:
                user_rows=api.get_list("User",filters={"name":user,"enabled":1},fields=["name"],limit_page_length=1)
                if user_rows: valid.append(user)
                else: result["invalid_users"]+=1
            if not valid:
                result["skipped_unconfigured"]+=1
                continue
            sent=0
            for user in valid:
                details=f"stage={stage}; recipient={user}; threshold_hours={parse_stage_threshold(intervals,stage)}"
                key=activity_key(row["name"],"Escalated",user,details,source_key=f"stage:{stage}:{user}")
                if api.get_list("Governance Exception Activity",filters={"idempotency_key":key},fields=["name"],limit_page_length=1):
                    continue
                log=api.get_doc({"doctype":"Notification Log","subject":f"Governance Exception Escalation: {row.get('title') or row['name']}",
                    "email_content":f"Exception {row['name']} ({row.get('severity')}) has reached escalation stage {stage}. Status: {row.get('status')}. Assigned to: {row.get('assigned_to') or 'Unassigned'}.",
                    "for_user":user,"type":"Alert","document_type":"Governance Exception","document_name":row["name"]})
                log.insert(ignore_permissions=True)
                append_activity(row["name"],"Escalated",actor="Administrator",details=f"stage={stage}; recipient={user}; threshold_hours={parse_stage_threshold(intervals,stage)}",source_key=f"stage:{stage}:{user}",api=api,now=now)
                sent+=1
            if sent:
                result["notifications"]+=sent
                result["escalated"]+=1
        except Exception as exc:
            result["errors"].append({"exception":row.get("name"),"error":str(exc)[:300]})
    return result


def parse_stage_threshold(intervals, stage):
    values=[int(x.strip()) for x in str(intervals).split(",") if x.strip()]
    return values[stage-1] if 0 < stage <= len(values) else None
