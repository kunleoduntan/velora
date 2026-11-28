"""Calendar-aware, deterministic precedence schedule date calculation."""
from datetime import date
from .calendar import add_working_days, working_days_between, is_working_day
from .scheduling import VALID_TYPES

def _iso(value):
    try: return date.fromisoformat(str(value))
    except (TypeError, ValueError): raise ValueError("Schedule dates must use ISO YYYY-MM-DD.")

def calculate_dated_schedule(activities, project_start, working_weekdays=(0,1,2,3,4), holidays=()):
    if not isinstance(activities, list): raise ValueError("activities must be a list.")
    start = _iso(project_start)
    rows = {}
    for a in activities:
        key = str(a.get("id") or "").strip()
        if not key or key in rows: raise ValueError("Activity IDs must be present and unique.")
        duration = a.get("duration")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration < 1: raise ValueError(f"{key}: duration must be a positive integer.")
        rows[key] = {"id":key,"duration":duration,"dependencies":a.get("dependencies",[]) or [],"constraint_start":a.get("constraint_start")}
    incoming={k:[] for k in rows}; outgoing={k:[] for k in rows}; indegree={k:0 for k in rows}
    for k,row in rows.items():
        deps=row["dependencies"]
        if not isinstance(deps,list): raise ValueError(f"{k}: dependencies must be a list.")
        for d in deps:
            pred=str(d.get("predecessor") or ""); typ=str(d.get("type","FS")).upper(); lag=d.get("lag",0)
            if pred not in rows or pred==k: raise ValueError(f"{k}: invalid predecessor {pred}.")
            if typ not in VALID_TYPES: raise ValueError(f"Unsupported dependency type: {typ}")
            if not isinstance(lag,int) or isinstance(lag,bool): raise ValueError("Dependency lag must be an integer working-day value.")
            incoming[k].append((pred,typ,lag)); outgoing[pred].append((k,typ,lag)); indegree[k]+=1
    queue=sorted(k for k,v in indegree.items() if v==0); order=[]
    while queue:
        k=queue.pop(0); order.append(k)
        for nxt,_,_ in outgoing[k]:
            indegree[nxt]-=1
            if indegree[nxt]==0: queue.append(nxt); queue.sort()
    if len(order)!=len(rows): raise ValueError("Dependency cycle detected.")
    es={}; ef={}
    for k in order:
        candidates=[start]
        if rows[k]["constraint_start"]: candidates.append(_iso(rows[k]["constraint_start"]))
        for pred,typ,lag in incoming[k]:
            pstart,pend=es[pred],ef[pred]
            if typ=="FS": candidate=add_working_days(pend,lag+1,working_weekdays,holidays)
            elif typ=="SS": candidate=add_working_days(pstart,lag,working_weekdays,holidays)
            elif typ=="FF": candidate=add_working_days(pend,lag,working_weekdays,holidays)
            else: candidate=add_working_days(pstart,lag,working_weekdays,holidays)
            candidate=_iso(candidate)
            if typ in {"FF","SF"}:
                candidate=_iso(add_working_days(candidate,-rows[k]["duration"],working_weekdays,holidays))
            candidates.append(candidate)
        chosen=max(candidates)
        while not is_working_day(chosen,working_weekdays,holidays):
            chosen=_iso(add_working_days(chosen,1,working_weekdays,holidays))
        es[k]=chosen
        ef[k]=_iso(add_working_days(chosen,rows[k]["duration"]-1,working_weekdays,holidays))
    finish=max(ef.values(),default=start)
    return {"project_start":start.isoformat(),"project_finish":finish.isoformat(),"duration_working_days":working_days_between(start.isoformat(),finish.isoformat(),working_weekdays,holidays),"activities":[{"id":k,"early_start":es[k].isoformat(),"early_finish":ef[k].isoformat(),"duration":rows[k]["duration"],"predecessors":[p for p,_,_ in incoming[k]]} for k in order],"method":"deterministic forward-pass; finish-to-finish/start-to-finish dates use duration offset; no float or resource-constrained optimisation"}
