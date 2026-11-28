"""Exception analytics and report helpers; consume SLA data from the existing SLA app."""
from collections import Counter
from datetime import date, datetime

ACTIVE = {"Open", "Assigned", "In Progress", "Escalated", "Pending Evidence"}


def _date(value):
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    try: return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError): return None


def build_exception_analytics(records=None, *, today=None, sla_records=None):
    """Aggregate exception records and externally supplied SLA facts without calculating SLA rules."""
    today = _date(today) if today else date.today()
    rows = [dict(r or {}) for r in (records or [])]
    statuses, severities, owners, ages = Counter(), Counter(), Counter(), Counter()
    active = overdue = critical = unassigned = escalated = 0
    resolved = closed = 0
    for row in rows:
        status = str(row.get("status") or "Open")
        severity = str(row.get("severity") or "Low")
        owner = str(row.get("assigned_to") or "Unassigned")
        statuses[status] += 1; severities[severity] += 1; owners[owner] += 1
        is_active = status in ACTIVE
        active += int(is_active)
        due = _date(row.get("due_date"))
        age = max(0, (today - due).days) if due and is_active else 0
        ages["0-6"] += int(0 <= age <= 6 and is_active)
        ages["7-13"] += int(7 <= age <= 13 and is_active)
        ages["14-29"] += int(14 <= age <= 29 and is_active)
        ages["30+"] += int(age >= 30 and is_active)
        overdue += int(age > 0)
        critical += int(severity == "Critical" and is_active)
        unassigned += int(is_active and owner == "Unassigned")
        escalated += int(status == "Escalated")
        resolved += int(status == "Resolved")
        closed += int(status == "Closed")
    sla = [dict(r or {}) for r in (sla_records or [])]
    # SLA statuses are accepted as supplied by the existing SLA engine. No target or breach calculation here.
    sla_status_counts = Counter(str(r.get("sla_status") or "Unknown") for r in sla)
    sla_breaches = sum(str(r.get("sla_status", "")).lower() in {"breached", "breach", "overdue"} for r in sla)
    return {
        "total": len(rows), "active": active, "overdue_active": overdue,
        "critical_active": critical, "unassigned_active": unassigned,
        "escalated": escalated, "resolved": resolved, "closed": closed,
        "status_counts": dict(statuses), "severity_counts": dict(severities),
        "owner_counts": dict(owners), "aging_buckets": dict(ages),
        "sla": {"records_received": len(sla), "breaches_reported_by_sla_engine": sla_breaches,
                "status_counts": dict(sla_status_counts), "integration_state": "external_data_consumed" if sla else "not_connected"},
        "as_of": today.isoformat(),
    }


def build_exception_report(records=None, *, filters=None, today=None, sla_records=None):
    """Return filtered report rows and analytics. Input rows must already be permission-filtered."""
    filters = dict(filters or {})
    rows = [dict(r or {}) for r in (records or [])]
    if filters.get("status"):
        rows = [r for r in rows if str(r.get("status")) == str(filters["status"])]
    if filters.get("severity"):
        rows = [r for r in rows if str(r.get("severity")) == str(filters["severity"])]
    if filters.get("assigned_to"):
        rows = [r for r in rows if str(r.get("assigned_to") or "") == str(filters["assigned_to"])]
    if filters.get("source_doctype"):
        rows = [r for r in rows if str(r.get("source_doctype") or "") == str(filters["source_doctype"])]
    if filters.get("from_date"):
        start = _date(filters["from_date"])
        rows = [r for r in rows if (d := _date(r.get("due_date"))) and start and d >= start]
    if filters.get("to_date"):
        end = _date(filters["to_date"])
        rows = [r for r in rows if (d := _date(r.get("due_date"))) and end and d <= end]
    rows.sort(key=lambda r: (str(r.get("severity") or ""), str(r.get("status") or ""), str(r.get("due_date") or "")))
    return {"rows": rows, "count": len(rows), "analytics": build_exception_analytics(rows, today=today, sla_records=sla_records),
            "filters": filters}
