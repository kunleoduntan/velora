"""Support Desk logic: choosing the agreement, running the service-level clocks, assigning tickets."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from velora import get_doc, get_list
from velora.meta.registry import registry
from velora.permissions import get_session

from . import sla as sla_calc

OPEN_STATES = ("Open", "In Progress", "Waiting on Customer")
DEFAULTS = {"default_priority": "Medium", "auto_close_days": 7, "escalation_user": "", "default_team": ""}


def cols(doctype: str) -> list[str]:
    return list(registry.get(doctype).column_names())


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_settings() -> dict:
    rows = get_list("Support Settings", fields=cols("Support Settings"), limit=1, ignore_permissions=True)
    out = dict(DEFAULTS)
    if rows:
        out.update({k: v for k, v in rows[0].items() if v not in (None, "")})
    return out


def holidays_for(sla: dict) -> set:
    name = sla.get("holiday_list")
    if not name or sla.get("round_the_clock"):
        return set()
    try:
        doc = get_doc("Holiday List", name, ignore_permissions=True)
        rows = doc.holiday_dates
        rows = json.loads(rows) if isinstance(rows, str) else (rows or [])
        return {date.fromisoformat(str(v)[:10]) for v in rows}
    except Exception:  # noqa: BLE001 - a missing holiday list must not stop a ticket being saved
        return set()


def find_sla(customer=None, category=None) -> dict | None:
    """Customer agreement, else category agreement, else the default one."""
    rows = get_list("Service Level Agreement", filters={"enabled": 1}, fields=cols("Service Level Agreement"), limit=500, ignore_permissions=True)
    for pick in (lambda r: customer and r.get("customer") == customer,
                 lambda r: category and r.get("category") == category and not r.get("customer"),
                 lambda r: r.get("is_default") and not r.get("customer") and not r.get("category")):
        for row in rows:
            if pick(row):
                return row
    return None


def target_hours(sla: dict, priority: str):
    """(first response hours, resolution hours) for a priority, from the agreement's child rows."""
    doc = get_doc("Service Level Agreement", sla["name"], ignore_permissions=True)
    for row in doc.targets:
        if row.priority == priority:
            return float(row.first_response_hours), float(row.resolution_hours)
    return None


def calendar_for(sla: dict) -> sla_calc.Calendar:
    return sla_calc.calendar_from(sla, holidays_for(sla))


def stamp_due_dates(ticket, now=None):
    """Set the agreement and both deadlines from the opening time and the priority."""
    sla = find_sla(ticket.customer, ticket.category)
    if not sla:
        ticket.sla = None
        ticket.first_response_due = ticket.resolution_due = None
        return None
    hours = target_hours(sla, ticket.priority)
    if not hours:
        ticket.sla = sla["name"]
        ticket.first_response_due = ticket.resolution_due = None
        return sla
    cal = calendar_for(sla)
    ticket.sla = sla["name"]
    ticket.first_response_due = sla_calc.add_working_seconds(cal, ticket.opened_on, hours[0] * 3600)
    ticket.resolution_due = sla_calc.add_working_seconds(cal, ticket.opened_on, hours[1] * 3600)
    return sla


def refresh_states(ticket, sla: dict | None = None, now=None):
    """Work out the response and resolution status from the clocks."""
    now = now or utcnow()
    if not ticket.sla or not ticket.first_response_due:
        ticket.response_sla = ticket.resolution_sla = ""
        return
    if sla is None:
        rows = get_list("Service Level Agreement", filters={"name": ticket.sla}, fields=cols("Service Level Agreement"), limit=1, ignore_permissions=True)
        sla = rows[0] if rows else {}
    cal = calendar_for(sla)
    warn = sla.get("warn_at_percent") or 80
    paused = ticket.status == "Waiting on Customer"
    # response
    if ticket.first_responded_on:
        ticket.response_sla = "Met" if ticket.first_responded_on <= ticket.first_response_due else "Breached"
    elif paused:
        ticket.response_sla = "Paused"
    else:
        ticket.response_sla = sla_calc.state(cal, ticket.opened_on, ticket.first_response_due, now, warn)
    # resolution
    if ticket.resolved_on:
        ticket.resolution_sla = "Met" if ticket.resolved_on <= ticket.resolution_due else "Breached"
    elif paused:
        ticket.resolution_sla = "Paused"
    else:
        ticket.resolution_sla = sla_calc.state(cal, ticket.opened_on, ticket.resolution_due, now, warn)


def shift_for_pause(ticket, paused_since, now):
    """After a customer wait, push the unmet deadlines out by the working time that was spent waiting."""
    sla = {}
    if ticket.sla:
        rows = get_list("Service Level Agreement", filters={"name": ticket.sla}, fields=cols("Service Level Agreement"), limit=1, ignore_permissions=True)
        sla = rows[0] if rows else {}
    cal = calendar_for(sla)
    waited = sla_calc.working_seconds_between(cal, paused_since, now)
    if waited <= 0:
        return
    if ticket.first_response_due and not ticket.first_responded_on:
        ticket.first_response_due = sla_calc.add_working_seconds(cal, ticket.first_response_due, waited)
    if ticket.resolution_due and not ticket.resolved_on:
        ticket.resolution_due = sla_calc.add_working_seconds(cal, ticket.resolution_due, waited)


# ---- assignment ------------------------------------------------------------------------------------------------
def resolve_team(ticket, settings=None) -> str | None:
    if ticket.team:
        return ticket.team
    if ticket.category:
        rows = get_list("Support Category", filters={"name": ticket.category}, fields=["default_team"], limit=1, ignore_permissions=True)
        if rows and rows[0].get("default_team"):
            return rows[0]["default_team"]
    return (settings or get_settings()).get("default_team") or None


def pick_agent(team_name: str) -> str | None:
    team = get_doc("Support Team", team_name, ignore_permissions=True)
    if team.disabled or team.assignment == "Nobody (the team picks)":
        return None
    members = [m.user for m in team.members if int(m.active or 0)]
    if not members:
        return None
    if team.assignment == "Least loaded":
        load = {m: 0 for m in members}
        for row in get_list("Support Ticket", filters=[["status", "in", list(OPEN_STATES)]], fields=["assigned_to"], limit=100000, ignore_permissions=True):
            if row.get("assigned_to") in load:
                load[row["assigned_to"]] += 1
        chosen = min(members, key=lambda m: (load[m], members.index(m)))
    else:
        last = team.last_assigned
        chosen = members[(members.index(last) + 1) % len(members)] if last in members else members[0]
    from velora_erp.finance.doctype._utils import db_update
    db_update(team, last_assigned=chosen)
    return chosen


def current_user() -> str:
    return get_session().user
