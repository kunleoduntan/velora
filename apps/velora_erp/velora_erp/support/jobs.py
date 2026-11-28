"""Scheduled support work: watch the service-level clocks and close tickets the customer has left resolved."""
from __future__ import annotations

from datetime import timedelta

from velora import get_doc, get_list

from velora_erp.finance.doctype._utils import db_update

from . import service as svc


def _notify(event: str, ticket, key: str) -> int:
    try:
        from velora_notify import engine
    except Exception:  # noqa: BLE001 - notifications are optional
        return 0
    try:
        return engine.trigger(event, ticket, key=key)
    except Exception:  # noqa: BLE001 - a failed message must never stop the watcher
        return 0


def check_sla(now=None) -> dict:
    """Every minute: move clocks from On track to At risk to Breached, tell people, escalate breaches."""
    now = now or svc.utcnow()
    stats = {"checked": 0, "at_risk": 0, "breached": 0, "escalated": 0}
    settings = svc.get_settings()
    for row in get_list("Support Ticket", filters=[["status", "in", list(svc.OPEN_STATES)], ["sla", "is", "set"]], fields=["name"], limit=100000, ignore_permissions=True):
        ticket = get_doc("Support Ticket", row["name"], ignore_permissions=True)
        before = (ticket.response_sla, ticket.resolution_sla)
        svc.refresh_states(ticket, now=now)
        after = (ticket.response_sla, ticket.resolution_sla)
        stats["checked"] += 1
        if before == after:
            continue
        events = []
        for kind, was, now_state in (("response", before[0], after[0]), ("resolution", before[1], after[1])):
            if now_state == "At risk" and was != "At risk":
                events.append(("support_sla_at_risk", kind))
                stats["at_risk"] += 1
            if now_state == "Breached" and was != "Breached":
                events.append(("support_sla_breached", kind))
                stats["breached"] += 1
        if any(e[0] == "support_sla_breached" for e in events):
            target = _escalation_target(ticket, settings)
            ticket.escalation_level = int(ticket.escalation_level or 0) + 1
            if target and ticket.assigned_to != target:
                ticket.assigned_to = target
            stats["escalated"] += 1
        states = {"response_sla": after[0], "resolution_sla": after[1]}
        ticket.save(ignore_permissions=True)
        db_update(ticket, **states)                  # the watcher's own clock reading stands (a save recalculates from the wall clock)
        for event, kind in events:
            _notify(event, ticket, key=f"{kind}:{ticket.escalation_level}")
    return stats


def _escalation_target(ticket, settings) -> str | None:
    if ticket.sla:
        rows = get_list("Service Level Agreement", filters={"name": ticket.sla}, fields=["escalate_to"], limit=1, ignore_permissions=True)
        if rows and rows[0].get("escalate_to"):
            return rows[0]["escalate_to"]
    if ticket.team:
        rows = get_list("Support Team", filters={"name": ticket.team}, fields=["team_lead"], limit=1, ignore_permissions=True)
        if rows and rows[0].get("team_lead"):
            return rows[0]["team_lead"]
    return settings.get("escalation_user") or None


def auto_close(now=None) -> int:
    """Daily: close resolved tickets the customer has not reopened within the configured days."""
    now = now or svc.utcnow()
    days = int(svc.get_settings().get("auto_close_days") or 0)
    if days <= 0:
        return 0
    cutoff = now - timedelta(days=days)
    closed = 0
    for row in get_list("Support Ticket", filters={"status": "Resolved"}, fields=["name", "resolved_on"], limit=100000, ignore_permissions=True):
        if row.get("resolved_on") and row["resolved_on"] <= cutoff:
            ticket = get_doc("Support Ticket", row["name"], ignore_permissions=True)
            ticket.status = "Closed"
            ticket.save(ignore_permissions=True)
            closed += 1
    return closed
