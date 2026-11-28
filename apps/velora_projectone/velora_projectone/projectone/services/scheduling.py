"""Deterministic CPM engine supporting FS, SS, FF and SF dependencies.

Durations and lags are integer working-day units. Calendar/holiday conversion
is a separate service; this engine does not pretend calendar dates are workdays.
"""
from collections import defaultdict, deque

VALID_TYPES = {"FS", "SS", "FF", "SF"}

def calculate_schedule(activities):
    if not isinstance(activities, list):
        raise ValueError("activities must be a list.")
    rows = {}
    for item in activities:
        if not isinstance(item, dict):
            raise ValueError("Each activity must be an object.")
        key = str(item.get("id") or "").strip()
        if not key or key in rows:
            raise ValueError("Activity IDs must be present and unique.")
        try: duration = int(item.get("duration"))
        except (TypeError, ValueError): raise ValueError(f"Activity {key}: duration must be an integer.")
        if duration < 0: raise ValueError(f"Activity {key}: duration cannot be negative.")
        rows[key] = {"id": key, "duration": duration}
    edges, indegree, succ = [], {k: 0 for k in rows}, defaultdict(list)
    for item in activities:
        key = str(item["id"])
        preds = item.get("dependencies", None)
        if preds is None:
            preds = [{"predecessor": p, "type": "FS", "lag": 0} for p in (item.get("predecessors", []) or [])]
        if not isinstance(preds, list): raise ValueError(f"Activity {key}: dependencies must be a list.")
        for dep in preds:
            if isinstance(dep, str): dep = {"predecessor": dep, "type": "FS", "lag": 0}
            p = str(dep.get("predecessor") or "")
            typ = str(dep.get("type", "FS")).upper()
            lag = int(dep.get("lag", 0))
            if p not in rows: raise ValueError(f"Activity {key}: unknown predecessor {p}.")
            if p == key: raise ValueError("An activity cannot depend on itself.")
            if typ not in VALID_TYPES: raise ValueError(f"Unsupported relationship type: {typ}")
            edges.append((p, key, typ, lag)); succ[p].append(key); indegree[key] += 1
    queue = deque(k for k, v in indegree.items() if v == 0); order = []
    while queue:
        k = queue.popleft(); order.append(k)
        for nxt in succ[k]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0: queue.append(nxt)
    if len(order) != len(rows): raise ValueError("Dependency cycle detected; schedule cannot be calculated.")
    es, ef = {}, {}
    incoming = defaultdict(list)
    for p, s, typ, lag in edges: incoming[s].append((p, typ, lag))
    for k in order:
        starts = [0]
        for p, typ, lag in incoming[k]:
            if typ == "FS": starts.append(ef[p] + lag)
            elif typ == "SS": starts.append(es[p] + lag)
            elif typ == "FF": starts.append(ef[p] + lag - rows[k]["duration"])
            elif typ == "SF": starts.append(es[p] + lag - rows[k]["duration"])
        es[k] = max(starts); ef[k] = es[k] + rows[k]["duration"]
    duration = max(ef.values(), default=0)
    # Backward pass uses relationship-specific latest-start constraints.
    ls, lf = {}, {}
    outgoing = defaultdict(list)
    for p, s, typ, lag in edges: outgoing[p].append((s, typ, lag))
    for k in reversed(order):
        latest = [duration - rows[k]["duration"]]
        for s, typ, lag in outgoing[k]:
            if typ == "FS": latest.append(ls[s] - lag - rows[k]["duration"])
            elif typ == "SS": latest.append(ls[s] - lag)
            elif typ == "FF": latest.append(lf[s] - lag - rows[k]["duration"])
            elif typ == "SF": latest.append(lf[s] - lag - rows[k]["duration"])
        ls[k] = min(latest); lf[k] = ls[k] + rows[k]["duration"]
    result = []
    for k in order:
        tf = ls[k] - es[k]
        result.append({"id": k, "duration": rows[k]["duration"], "early_start": es[k], "early_finish": ef[k], "late_start": ls[k], "late_finish": lf[k], "total_float": tf, "critical": tf == 0})
    return {"duration": duration, "activities": result, "critical_activities": [r["id"] for r in result if r["critical"]], "relationship_support": sorted({e[2] for e in edges} or {"FS"}), "time_unit": "working-day units; calendar conversion not applied"}
