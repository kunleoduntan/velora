"""Staff routes to invite, reset and suspend portal contacts."""
from fastapi import Body, Request
from velora import get_list
from velora.meta.registry import registry
from velora.permissions import check_permission
from velora_erp import portal_service as svc


def _can(ptype):
    check_permission(registry.get("Portal Account"), ptype)


def install_routes(app, scope, run):
    base = "/api/portal-admin"

    @app.get(f"{base}/accounts")
    def accounts(request: Request):
        def fn():
            _can("read")
            from velora import portal as core
            waiting = core.reset_requests()
            items = get_list("Portal Account", fields=["name", "email", "full_name", "portal_type", "customer", "supplier", "employee", "status", "last_invited"], order_by="modified desc", limit=500)
            return {"items": [{**i, "reset_requested": i["email"] in waiting} for i in items]}
        return run(request, fn)

    @app.post(f"{base}/invite")
    def invite(request: Request, body: dict = Body(...)):
        def fn():
            _can("create")
            return svc.invite(body.get("email"), body.get("full_name"), body.get("portal_type"), body.get("party"))
        return run(request, fn)

    @app.post(f"{base}/reset")
    def reset(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return svc.reset_password(body.get("email"))
        return run(request, fn)

    @app.post(f"{base}/status")
    def status(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return svc.set_status(body.get("email"), body.get("status"))
        return run(request, fn)
