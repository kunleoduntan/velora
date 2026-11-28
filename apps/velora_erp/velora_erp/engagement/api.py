"""Engagement routes: preview a template, release held messages. Installed by velora_erp.api_routes."""
from __future__ import annotations

from fastapi import Body, FastAPI, Request

from velora import get_list, throw
from velora.meta.registry import registry
from velora.permissions import check_permission

from . import service


def _need(doctype: str, perm: str):
    check_permission(registry.get(doctype), perm)


def install_engagement_routes(app: FastAPI, run):
    @app.get("/api/engagement/preview")
    def preview(request: Request, template: str, party_type: str = "Customer", party: str = ""):
        def fn():
            _need("Moment Template", "read")
            if party_type not in ("Customer", "Supplier", "Employee"):
                throw("Unknown party type.")
            return service.preview(template, party_type, party or None)
        return run(request, fn)

    @app.get("/api/engagement/held")
    def held(request: Request):
        def fn():
            _need("Engagement Log", "read")
            return {"items": get_list("Engagement Log", filters=[["status", "=", "Held"]], fields=["name", "moment_date", "kind", "party_type", "party", "party_name", "subject", "email"],
                                      order_by="moment_date desc", limit=500)}
        return run(request, fn)

    @app.post("/api/engagement/release")
    def release(request: Request, body: dict = Body(...)):
        def fn():
            _need("Engagement Log", "write")
            name = body.get("name")
            return {"name": name, "status": service.release(name)} if name else {"released": service.release_all_held()}
        return run(request, fn)

    @app.post("/api/engagement/run")
    def run_now(request: Request):
        def fn():
            _need("Engagement Settings", "write")
            return service.run()
        return run(request, fn)
