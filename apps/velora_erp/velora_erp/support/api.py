"""Support routes: desk numbers, replying, assigning. Installed by velora_erp.api_routes."""
from __future__ import annotations

from fastapi import Body, FastAPI, Request

from velora import get_doc, throw
from velora.meta.registry import registry
from velora.permissions import check_permission, get_session

from .desk import summary


def reply(name: str, message: str, kind: str = "Reply to customer", status: str | None = None):
    message = (message or "").strip()
    if not message:
        throw("Write the message first.")
    if kind not in ("Reply to customer", "Internal note", "Customer reply"):
        throw("Unknown kind of reply.")
    ticket = get_doc("Support Ticket", name)
    row = {"kind": kind, "message": message}
    ticket.append("replies", row)
    if status:
        ticket.status = status
    elif kind == "Reply to customer" and ticket.status == "Open":
        ticket.status = "In Progress"
    ticket.save()
    return {"name": ticket.name, "status": ticket.status, "response_sla": ticket.response_sla}


def install_support_routes(app: FastAPI, run):
    @app.get("/api/support/summary")
    def summary_route(request: Request):
        def fn():
            check_permission(registry.get("Support Ticket"), "read")
            return summary(get_session().user)
        return run(request, fn)

    @app.post("/api/support/tickets/{name}/reply")
    def reply_route(name: str, request: Request, body: dict = Body(default={})):
        def fn():
            return reply(name, body.get("message"), body.get("kind") or "Reply to customer", body.get("status"))
        return run(request, fn)

    @app.post("/api/support/tickets/{name}/assign")
    def assign_route(name: str, request: Request, body: dict = Body(default={})):
        def fn():
            ticket = get_doc("Support Ticket", name)
            ticket.assigned_to = (body.get("user") or "").strip() or None
            ticket.save()
            return {"name": ticket.name, "assigned_to": ticket.assigned_to}
        return run(request, fn)
