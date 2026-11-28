"""Programme intelligence on real data: the schedule, risk and cost/resource figures are read from the projects the signed-in user may see.

Browsers send only a programme id and assumptions; the rows come from the database under the user's own permissions."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from velora import get_list, new_doc
from velora.exceptions import DoesNotExistError, ValidationError

from .host_sources import AccountingSource
from .projectone.integrations.source_readers import ReadQuery

_RELATION = {"Finish to Start": "FS", "Start to Start": "SS", "Finish to Finish": "FF", "Start to Finish": "SF"}
_OPEN = ("Cancelled", "Completed")


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _weekdays(text):
    days = []
    for part in str(text or "").replace(";", ",").replace(" ", ",").split(","):
        if part.strip().isdigit() and 0 <= int(part) <= 6 and int(part) not in days:
            days.append(int(part))
    return days or [0, 1, 2, 3, 4]


def _holidays(text):
    out = []
    for part in str(text or "").replace(";", ",").replace("\n", ",").split(","):
        d = _day(part.strip())
        if d and d.isoformat() not in out:
            out.append(d.isoformat())
    return out


class VeloraProgrammeData:
    """read_programme_schedule / read_programme_risk_model / read_programme_cost_resource_position, as the routes expect."""

    def _projects(self, programme_id):
        if not get_list("Project Programme", filters=[["name", "=", programme_id]], fields=["name"], limit=1):
            raise DoesNotExistError(f"Programme {programme_id} was not found, or you may not read it.")
        rows = get_list("Project", filters=[["programme", "=", programme_id]], limit=500,
                        fields=["name", "title", "start_date", "end_date", "currency", "approved_budget", "forecast_cost", "resource_calendar", "status"])
        return [r for r in rows if r["status"] not in ("Cancelled",)]

    def _calendar(self, projects):
        ids = [p["resource_calendar"] for p in projects if p.get("resource_calendar")]
        flt = [["name", "=", ids[0]]] if ids else [["is_default", "=", 1]]
        rows = get_list("Resource Calendar", filters=flt, fields=["working_weekdays", "holiday_dates"], limit=1)
        return (_weekdays(rows[0]["working_weekdays"]), _holidays(rows[0]["holiday_dates"])) if rows else ([0, 1, 2, 3, 4], [])

    def read_programme_schedule(self, actor, programme_id):
        projects = self._projects(programme_id)
        weekdays, holidays = self._calendar(projects)
        names = [p["name"] for p in projects]
        tasks = get_list("Project Task", filters=[["project", "in", names]], limit=5000,
                         fields=["name", "title", "project", "planned_start", "planned_finish", "duration_days", "status"]) if names else []
        tasks = [t for t in tasks if t["status"] != "Cancelled"]
        known = {t["name"] for t in tasks}
        links = get_list("Task Dependency", filters=[["project", "in", names], ["active", "=", 1]], limit=10000,
                         fields=["predecessor", "successor", "relationship", "lag_days"]) if names else []
        deps = {}
        for l in links:
            if l["predecessor"] in known and l["successor"] in known:
                deps.setdefault(l["successor"], []).append({"predecessor": l["predecessor"], "type": _RELATION.get(l["relationship"], "FS"), "lag": int(l["lag_days"] or 0)})
        starts = [d for d in (_day(t["planned_start"]) for t in tasks) if d] or [d for d in (_day(p["start_date"]) for p in projects) if d]
        activities = []
        for t in tasks:
            duration = int(t["duration_days"] or 0)
            s, f = _day(t["planned_start"]), _day(t["planned_finish"])
            if not duration and s and f and f >= s:
                duration = (f - s).days + 1
            activities.append({"id": t["name"], "name": t["title"], "duration": max(duration, 0), "dependencies": deps.get(t["name"], [])})
        return {"activities": activities, "project_start": (min(starts) if starts else date.today()).isoformat(),
                "working_weekdays": weekdays, "holidays": holidays}

    def read_programme_risk_model(self, actor, programme_id):
        source = self.read_programme_schedule(actor, programme_id)
        projects = self._projects(programme_id)
        names = [p["name"] for p in projects]
        rows = get_list("Project Risk", filters=[["project", "in", names]], limit=2000,
                        fields=["name", "probability", "status", "min_days", "most_likely_days", "max_days",
                                "min_cost", "most_likely_cost", "max_cost"]) if names else []
        risks = []
        for r in rows:
            if r["status"] in _OPEN or not r["probability"]:
                continue
            p = float(r["probability"])
            p = p / 5 if p <= 5 else p / 100 if p <= 100 else 1.0
            lo, mid, hi = (int(r[k] or 0) for k in ("min_days", "most_likely_days", "max_days"))
            clo, cmid, chi = (float(r[k] or 0) for k in ("min_cost", "most_likely_cost", "max_cost"))
            risks.append({"risk_id": r["name"], "probability": p, "min_days": lo, "most_likely_days": max(mid, lo), "max_days": max(hi, mid, lo),
                          "min_cost": clo, "most_likely_cost": max(cmid, clo), "max_cost": max(chi, cmid, clo)})
        currencies = {p["currency"] for p in projects if p.get("currency")}
        base = sum(float(p["approved_budget"] or 0) for p in projects) if len(currencies) == 1 else 0
        return {**source, "risks": risks, "base_cost": base}

    def read_programme_cost_resource_position(self, actor, programme_id):
        projects = self._projects(programme_id)
        names = [p["name"] for p in projects]
        weekdays, holidays = self._calendar(projects)
        allocations = get_list("Project Resource Allocation", filters=[["project", "in", names]], limit=5000,
                               fields=["project", "resource", "start_date", "end_date", "planned_hours", "resource_profile", "status"]) if names else []
        allocations = [a for a in allocations if a["status"] != "Cancelled"]
        dates = [d for a in allocations for d in (_day(a["start_date"]), _day(a["end_date"])) if d]
        working = 0
        if dates:
            day, end = min(dates), max(dates)
            while day <= end:
                working += day.weekday() in weekdays and day.isoformat() not in holidays
                day += timedelta(days=1)
        profiles = {p["name"]: float(p["daily_capacity_hours"] or 8) for p in get_list(
            "Resource Profile", fields=["name", "daily_capacity_hours"], limit=5000)}
        accounting, out = AccountingSource(), []
        for p in projects:
            position = next(iter(accounting.read(ReadQuery("site", "project_positions", project_id=p["name"]))), None) or {}
            currency = p.get("currency") or position.get("currency")
            if not currency:
                raise ValidationError(f"Project {p['name']} has no currency; set one before comparing programme costs.")
            if position.get("currency") and position["currency"] != currency:
                raise ValidationError(f"Project {p['name']} is in {currency} but its ledger is in {position['currency']}; amounts are not converted.")
            actual = float(position.get("actual_cost") or 0)
            resources = {}
            for a in (x for x in allocations if x["project"] == p["name"]):
                r = resources.setdefault(a["resource"], {"resource_id": a["resource"], "demand_hours": 0.0,
                                                          "capacity_hours": profiles.get(a["resource_profile"], 8.0) * working})
                r["demand_hours"] += float(a["planned_hours"] or 0)
            out.append({"project_id": p["name"], "currency": currency, "approved_budget": float(p["approved_budget"] or 0),
                        "actual_cost": max(actual, 0),
                        "forecast_cost": float(p["forecast_cost"]) if p.get("forecast_cost") not in (None, "") else max(actual, 0), "resources": list(resources.values())})
        return {"projects": out}


def submit_intervention(actor, envelope):
    """Create the corrective action as the signed-in user, then send it to the approval workflow if one is set up."""
    doc = new_doc("Project Corrective Action", title=envelope["title"], exception_id=envelope["exception_id"],
                  action_owner=envelope["owner"], due_date=envelope["due_date"] or None, requested_by=envelope["requested_by"],
                  project=envelope.get("project") or None, status="Draft")
    doc.insert()
    from .velora_host import VeloraWorkflow
    try:
        VeloraWorkflow().submit(actor, "Project Corrective Action", doc.name, envelope["workflow_action"])
        routed = True
    except ValidationError:
        routed = False  # no workflow drawn for this DocType yet: the action stays a Draft for its owner
    return {"name": doc.name, "status": doc.status, "sent_for_approval": routed}
