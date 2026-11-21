"""The welcome page's data and the standalone tutorial.

  GET /api/welcome   what just happened (install / update / upgrade ...), what is installed, this company's addresses, where the tutorial is
  GET /tutorial      the full tutorial as ONE self-contained HTML page (no sign-in needed, works offline, prints well)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .. import __version__, eventlog
from .. import site as site_mod
from ..apps import BUNDLED_APPS, _hooks
from ..company import current_company
from ..permissions import get_session

TUTORIAL = Path(__file__).resolve().parent.parent / "static" / "tutorial.html"
POWERED_BY = "Velora BiZ Solutions"


def _apps() -> list[dict]:
    out = []
    for a in site_mod.current().installed_apps():
        try:
            h = _hooks(a)
            out.append({"name": a, "title": getattr(h, "app_title", None) or a, "description": getattr(h, "app_description", "") or "", "built_in": a in BUNDLED_APPS})
        except Exception:  # noqa: BLE001 - an app whose hooks cannot load is still listed
            out.append({"name": a, "title": a, "description": "", "built_in": a in BUNDLED_APPS})
    return out


def install_welcome_routes(app: FastAPI, scope, run, workspace=None, plane=None):
    @app.get("/api/welcome")
    def welcome(request: Request):
        def fn():
            s = get_session()
            co = current_company()
            events = eventlog.recent(workspace, 8)
            apps = _apps()
            names = {a["name"] for a in apps}
            domains = []
            if plane is not None and co is not None:
                domains = [{"domain": d["domain"], "primary": bool(d["is_primary"]), "tls": bool(d["tls"]), "locked": bool(d["locked"])} for d in plane.registry.list_domains(co.id)]
            return {"product": "Velora", "powered_by": POWERED_BY, "version": __version__, "user": s.user, "is_admin": s.user == "Administrator" or "System Manager" in s.roles,
                    "company": {"id": co.id, "name": co.name} if co else None, "latest": events[0] if events else None, "events": events, "apps": apps,
                    "features": {"notifications": "velora_notify" in names, "search": "velora_search" in names, "accounts": "velora_accounts" in names},
                    "domains": domains, "host": (request.headers.get("host") or "").split(":")[0], "tutorial_url": "/tutorial", "platform": plane is not None}
        return run(request, fn)

    @app.get("/tutorial", include_in_schema=False)
    @app.get("/tutorial/", include_in_schema=False)
    def tutorial():
        if not TUTORIAL.exists():
            return JSONResponse({"message": "The tutorial file is missing from this installation."}, status_code=404)
        return FileResponse(TUTORIAL, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})
