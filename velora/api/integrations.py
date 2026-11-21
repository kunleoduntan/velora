"""Company-local integration administration endpoints."""
from __future__ import annotations
from datetime import datetime
from fastapi import Body, FastAPI, Request
from ..exceptions import ValidationError
from .. import integration_engine as ie

def install_integration_routes(app: FastAPI, scope, run):
    @app.get("/api/integrations/api-keys")
    def api_keys(request: Request):
        return run(request, ie.list_api_keys)

    @app.post("/api/integrations/api-keys")
    def create_api_key(request: Request, body: dict = Body(...)):
        def fn():
            expiry = body.get("expires_on")
            if expiry:
                try: expiry = datetime.fromisoformat(expiry)
                except (TypeError, ValueError): raise ValidationError("expires_on must be an ISO datetime")
            return ie.issue_api_key(body.get("label"), body.get("scopes"), expiry)
        return run(request, fn)

    @app.delete("/api/integrations/api-keys/{key_id}")
    def revoke_api_key(key_id: str, request: Request):
        def fn():
            if not ie.revoke_api_key(key_id):
                raise ValidationError("API key was not found or is already revoked")
            return {"revoked": True}
        return run(request, fn)

    @app.get("/api/integrations/webhooks")
    def webhooks(request: Request):
        def fn():
            ie._manager(); ie.ensure()
            from sqlalchemy import select
            with ie.db.transaction() as c:
                rows=c.execute(select(ie._hooks.c.id, ie._hooks.c.label, ie._hooks.c.target_url,
                    ie._hooks.c.events, ie._hooks.c.active, ie._hooks.c.created_by, ie._hooks.c.created_on)
                    .order_by(ie._hooks.c.created_on.desc())).mappings().all()
            return [dict(x) for x in rows]
        return run(request, fn)

    @app.post("/api/integrations/webhooks")
    def create_webhook(request: Request, body: dict = Body(...)):
        return run(request, lambda: ie.create_webhook(body.get("label"), body.get("target_url"), body.get("events")))

    @app.delete("/api/integrations/webhooks/{subscription_id}")
    def deactivate_webhook(subscription_id: str, request: Request):
        def fn():
            if not ie.deactivate_webhook(subscription_id):
                raise ValidationError("Webhook subscription was not found or is already inactive")
            return {"deactivated": True}
        return run(request, fn)

    @app.post("/api/integrations/webhook-deliveries/{delivery_id}/retry")
    def retry_webhook(delivery_id: str, request: Request):
        def fn():
            if not ie.retry_webhook(delivery_id):
                raise ValidationError("Only a dead webhook delivery can be retried")
            return {"queued": True}
        return run(request, fn)

    @app.post("/api/integrations/messages")
    def send_message(request: Request, body: dict = Body(...)):
        def fn():
            ie._manager()
            channel=str(body.get("channel") or "").upper()
            if channel not in ("SMS", "WHATSAPP"):
                raise ValidationError("channel must be SMS or WHATSAPP")
            result=ie.send_message(channel, body.get("recipient"), body.get("message"), body.get("config") or {})
            return {"accepted": True, "provider_response": str(result)[:500]}
        return run(request, fn)

    @app.get("/api/integrations/logs")
    def logs(request: Request, limit: int = 100):
        return run(request, lambda: ie.integration_logs(limit))
