"""Numbers for the Support Desk page."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from velora import get_list

from . import service as svc

SEVERITY = {"Breached": 0, "At risk": 1, "On track": 2, "Paused": 3, "Met": 4, "": 5}
PRIORITY_RANK = {"Urgent": 0, "High": 1, "Medium": 2, "Low": 3}


def _hours(a, b):
    return (b - a).total_seconds() / 3600 if a and b else None


def summary(user: str | None = None, now=None) -> dict:
    now = now or svc.utcnow()
    fields = ["name", "subject", "status", "priority", "category", "customer", "assigned_to", "team", "opened_on", "first_response_due", "first_responded_on",
              "resolution_due", "resolved_on", "response_sla", "resolution_sla", "escalation_level", "satisfaction", "closed_on"]
    rows = get_list("Support Ticket", fields=fields, limit=100000, ignore_permissions=True)
    open_rows = [r for r in rows if r["status"] in svc.OPEN_STATES]

    def worst(r):
        return min(SEVERITY.get(r.get("response_sla") or "", 5) if not r.get("first_responded_on") else 5, SEVERITY.get(r.get("resolution_sla") or "", 5))

    queue = sorted(open_rows, key=lambda r: (worst(r), PRIORITY_RANK.get(r["priority"], 9), r["opened_on"] or now))
    for r in queue:
        r["age_hours"] = round(_hours(r["opened_on"], now) or 0, 1)
    resolved = [r for r in rows if r.get("resolved_on")]
    responded = [r for r in rows if r.get("first_responded_on") and r.get("opened_on")]
    scores = [int(r["satisfaction"]) for r in rows if r.get("satisfaction")]
    met = [r for r in rows if r.get("resolution_sla") in ("Met", "Breached")]
    days = [(now - timedelta(days=i)).date() for i in range(13, -1, -1)]
    created, solved = Counter(r["opened_on"].date() for r in rows if r.get("opened_on")), Counter(r["resolved_on"].date() for r in resolved)
    workload = defaultdict(lambda: {"open": 0, "breached": 0})
    for r in open_rows:
        w = workload[r.get("assigned_to") or "Unassigned"]
        w["open"] += 1
        w["breached"] += 1 if "Breached" in (r.get("response_sla"), r.get("resolution_sla")) else 0
    age = Counter()
    for r in open_rows:
        h = _hours(r["opened_on"], now) or 0
        age["Under 1 day" if h < 24 else "1 to 3 days" if h < 72 else "3 to 7 days" if h < 168 else "Over 7 days"] += 1
    by_category = Counter(r.get("category") or "Uncategorised" for r in open_rows)
    return {
        "kpis": {
            "open": len(open_rows),
            "unassigned": sum(1 for r in open_rows if not r.get("assigned_to")),
            "mine": sum(1 for r in open_rows if user and r.get("assigned_to") == user),
            "at_risk": sum(1 for r in open_rows if "At risk" in (r.get("response_sla"), r.get("resolution_sla"))),
            "breached": sum(1 for r in open_rows if "Breached" in (r.get("response_sla"), r.get("resolution_sla"))),
            "waiting": sum(1 for r in open_rows if r["status"] == "Waiting on Customer"),
            "resolved_today": sum(1 for r in resolved if r["resolved_on"].date() == now.date()),
            "avg_first_response_hours": round(sum(_hours(r["opened_on"], r["first_responded_on"]) for r in responded) / len(responded), 1) if responded else None,
            "avg_resolution_hours": round(sum(_hours(r["opened_on"], r["resolved_on"]) for r in resolved if r.get("opened_on")) / len(resolved), 1) if resolved else None,
            "sla_met_percent": round(100 * sum(1 for r in met if r["resolution_sla"] == "Met") / len(met), 1) if met else None,
            "satisfaction": round(sum(scores) / len(scores), 2) if scores else None,
        },
        "queue": queue[:50],
        "workload": sorted(({"agent": k, **v} for k, v in workload.items()), key=lambda x: -x["open"]),
        "ageing": [{"bucket": b, "count": age.get(b, 0)} for b in ("Under 1 day", "1 to 3 days", "3 to 7 days", "Over 7 days")],
        "trend": [{"date": d.isoformat(), "opened": created.get(d, 0), "resolved": solved.get(d, 0)} for d in days],
        "categories": [{"category": k, "count": v} for k, v in by_category.most_common(8)],
    }
