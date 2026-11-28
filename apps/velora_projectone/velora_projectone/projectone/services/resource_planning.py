"""Resource skill matching and transparent priority-first levelling heuristic."""
from decimal import Decimal
from .resources import _decimal

def match_resource_skills(requirements, resources):
    output=[]
    for req in requirements:
        needed=set(req.get("skills",[])); candidates=[]
        for resource in resources:
            if resource.get("active",True) is False: continue
            have=set(resource.get("skills",[])); missing=sorted(needed-have)
            if not missing: candidates.append({"resource_id":resource.get("resource_id"),"match_score":len(needed)/max(1,len(needed)),"skills_matched":sorted(needed)})
        output.append({"activity_id":req.get("activity_id"),"candidates":sorted(candidates,key=lambda x:str(x["resource_id"]))})
    return output

def level_allocations(activities, capacities):
    """Allocate each activity's requested hours in priority/start/id order.

    This is a deterministic greedy heuristic, not an optimal RCPSP solver.
    Each allocation consumes a resource-period bucket; unplaced hours remain visible.
    """
    remaining={k:_decimal(v,"capacity") for k,v in capacities.items()}
    results=[]
    ordered=sorted(activities,key=lambda a:(int(a.get("priority",999)),str(a.get("planned_start","")),str(a.get("id",""))))
    for activity in ordered:
        rid=str(activity.get("resource_id") or ""); period=str(activity.get("period") or "")
        hours=_decimal(activity.get("hours",0),"hours"); key=(rid,period)
        available=remaining.get(key,Decimal("0")); assigned=min(hours,available); remaining[key]=available-assigned
        results.append({"activity_id":activity.get("id"),"resource_id":rid,"period":period,"requested_hours":hours,"assigned_hours":assigned,"unassigned_hours":hours-assigned,"levelled":assigned==hours})
    return {"allocations":results,"unassigned_hours":sum((r["unassigned_hours"] for r in results),Decimal("0")),"heuristic":"priority, planned start, activity ID; no automatic schedule-date mutation"}
