"""Risk, issue, change and quality gate controls."""
from decimal import Decimal

def assess_risk(risk):
    p=int(risk.get("probability",0)); impact=int(risk.get("impact",0))
    if p not in range(1,6) or impact not in range(1,6): raise ValueError("Risk probability and impact must be integers from 1 to 5.")
    score=p*impact
    band="Critical" if score>=20 else "High" if score>=12 else "Medium" if score>=6 else "Low"
    if not (risk.get("risk_owner") or risk.get("owner")): raise ValueError("Every active risk must have an accountable owner.")
    return {"risk_score":score,"severity":band,"requires_response_plan":score>=6,"requires_escalation":score>=20}

def validate_change_request(change):
    required=("change_id","project_id","description","requested_by","impact_assessment")
    missing=[k for k in required if not str(change.get(k) or "").strip()]
    if missing: raise ValueError("Change request is incomplete: "+", ".join(missing))
    if change.get("status")=="Approved" and not change.get("approval_reference"): raise ValueError("Approved change requires an approval reference.")
    if change.get("status")=="Implemented" and change.get("status_before_implementation")!="Approved": raise ValueError("Only approved changes may be implemented.")
    return True

def quality_gate(deliverable):
    required=("deliverable_id","acceptance_criteria","inspector","inspection_date")
    missing=[k for k in required if not deliverable.get(k)]
    if missing: raise ValueError("Quality inspection requires: "+", ".join(missing))
    result=deliverable.get("result")
    if result not in {"Accepted","Rejected","Accepted with Comments"}: raise ValueError("Unsupported quality result.")
    if result=="Accepted with Comments" and not deliverable.get("comments"): raise ValueError("Conditional acceptance requires comments.")
    return {"result":result,"completion_allowed":result=="Accepted","reinspection_required":result=="Rejected"}
