"""Explainable, advisory-only project insights. Never mutates business records."""
def project_insights(project):
    findings=[]
    progress=float(project.get("progress_percent",0) or 0)
    if project.get("status")=="Active" and not project.get("approved_baseline"):
        findings.append({"code":"BASELINE_MISSING","severity":"High","recommendation":"Complete and approve the schedule baseline before relying on schedule variance reporting."})
    if project.get("schedule_variance_days",0)>0:
        findings.append({"code":"SCHEDULE_SLIP","severity":"High","recommendation":"Review the critical path, remaining durations, dependency quality and recovery options."})
    if project.get("budget_variance",0)<0:
        findings.append({"code":"COST_PRESSURE","severity":"High","recommendation":"Reconcile actual cost and open commitments, then submit a controlled forecast or budget change if justified."})
    if project.get("critical_risk_count",0)>0:
        findings.append({"code":"CRITICAL_RISKS","severity":"Critical","recommendation":"Escalate critical risks to the sponsor and record funded response owners and due dates."})
    if progress>=100 and project.get("status") not in {"Completed","Closed"}:
        findings.append({"code":"COMPLETION_REVIEW","severity":"Medium","recommendation":"Verify deliverable acceptance, financial reconciliation and handover evidence before closure."})
    return {"project_id":project.get("name") or project.get("project_id"),"findings":findings,"advisory_only":True,"records_changed":False,"requires_human_approval":True}
