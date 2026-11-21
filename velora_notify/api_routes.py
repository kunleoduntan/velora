"""Broadcast Centre and notification test-send routes."""
from __future__ import annotations

from datetime import datetime

from fastapi import Body, FastAPI, Request

from velora import get_list, throw
from velora.meta.registry import registry
from velora.permissions import check_permission

from . import channels, outbox
from .broadcast import service


def _when(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "").replace("T", " ")[:19])
    except ValueError:
        throw("The time must look like 2026-12-01 09:30 (UTC).")


def centre_summary() -> dict:
    rows = get_list("Broadcast", fields=["name", "title", "channel", "status", "total_recipients", "sent_count", "failed_count", "opted_out_count", "scheduled_for", "started_on", "modified"],
                    order_by="modified desc", limit=500)
    cfg = channels.settings()
    month = datetime.utcnow().strftime("%Y-%m")
    by_channel = {c: {"broadcasts": 0, "sent": 0, "failed": 0} for c in ("Email", "SMS", "WhatsApp")}
    for r in rows:
        if str(r.get("started_on") or "")[:7] == month:
            b = by_channel[r["channel"]]
            b["broadcasts"] += 1
            b["sent"] += r.get("sent_count") or 0
            b["failed"] += r.get("failed_count") or 0
    return {"recent": rows[:25], "scheduled": [r for r in rows if r["status"] == "Scheduled"], "running": [r for r in rows if r["status"] == "Sending"], "by_channel": by_channel,
            "opt_outs": len(get_list("Communication Opt-Out", fields=["name"], limit=100000)),
            "gateways": {"Email": bool((cfg.get("email") or {}).get("host")), "SMS": bool(cfg.get("sms")), "WhatsApp": bool(cfg.get("whatsapp")), "base_url": bool(cfg.get("base_url"))},
            "outbox": outbox.stats()}


def install_routes(app: FastAPI, scope, run):
    from velora import portal
    portal.register_public_action("unsubscribe", service.unsubscribe_page)

    def need(ptype="write"):
        check_permission(registry.get("Broadcast"), ptype)

    @app.get("/api/broadcast-centre/summary")
    def summary(request: Request):
        def fn():
            need("read")
            return centre_summary()
        return run(request, fn)

    @app.post("/api/broadcasts/{name}/build")
    def build(name: str, request: Request):
        def fn():
            need()
            return service.build_recipients(name)
        return run(request, fn)

    @app.get("/api/broadcasts/{name}/preview")
    def preview(name: str, request: Request):
        def fn():
            need("read")
            return service.preview(name)
        return run(request, fn)

    @app.post("/api/broadcasts/{name}/send")
    def send(name: str, request: Request, body: dict = Body(default={})):
        def fn():
            need()
            return service.send(name, _when(body.get("send_at")))
        return run(request, fn)

    @app.post("/api/broadcasts/{name}/test")
    def test(name: str, request: Request, body: dict = Body(default={})):
        def fn():
            need()
            return service.send_test(name, str(body.get("to") or ""))
        return run(request, fn)

    @app.post("/api/broadcasts/{name}/cancel")
    def cancel(name: str, request: Request):
        def fn():
            need()
            return service.cancel(name)
        return run(request, fn)

    @app.post("/api/broadcasts/{name}/sync")
    def sync(name: str, request: Request):
        def fn():
            need("read")
            return service.sync(name)
        return run(request, fn)

    @app.post("/api/notify/rules/{name}/test")
    def test_rule(name: str, request: Request, body: dict = Body(default={})):
        def fn():
            check_permission(registry.get("Notification Rule"), "read")
            return service.test_rule(name, str(body.get("doc") or ""), str(body.get("to") or ""))
        return run(request, fn)

    @app.post("/api/notification-settings/test-gateway")
    def test_gateway(request: Request, body: dict = Body(default={})):
        def fn():
            from velora.permissions import get_session
            sess = get_session()
            if not (sess.user == "Administrator" or "System Manager" in sess.roles):
                from velora.exceptions import PermissionDenied
                raise PermissionDenied("Only a System Manager can do that")
            channel = str(body.get("channel") or "")
            if channel not in ("Email", "SMS", "WhatsApp"):
                throw("Choose Email, SMS or WhatsApp.")
            address = service.clean_address(body.get("to"), channel)
            if address is None:
                throw(f"Enter a valid {'email address' if channel == 'Email' else 'phone number'}.")
            return service.deliver_now(channel, address, "Velora test message", "If you can read this, the " + channel + " channel is working.")
        return run(request, fn)
