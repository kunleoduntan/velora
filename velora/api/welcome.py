"""The welcome page's data and the standalone tutorial.

  GET /api/welcome   what just happened (install / update / upgrade ...), what is installed, this company's addresses, where the tutorial is
  GET /tutorial      the full tutorial as ONE self-contained HTML page (no sign-in needed, works offline, prints well)
  GET /guide/<app>   an installed app's own how-to guide (its `app_guide` hook), same style of page
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


def guide_file(app: str) -> Path | None:
    """The how-to guide an installed app ships: its hook `app_guide` is a path (wildcards allowed, newest wins) inside the app's own package.

    A guide is a public document that ships in the app's package, like /tutorial, so no company or sign-in is needed to find it (on a server with
    many companies there is no "current" company at this point). Nothing outside the package, and nothing but .html, is ever served."""
    import importlib
    import importlib.util
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,60}", app or "") or importlib.util.find_spec(app) is None:
        return None
    try:
        h = _hooks(app)
        pattern = getattr(h, "app_guide", None) if h else None
        if not pattern or ".." in pattern or pattern.startswith(("/", "\\")):
            return None
        root = Path(importlib.import_module(app).__file__).resolve().parent
        found = sorted(f for f in root.glob(pattern) if f.suffix == ".html" and f.resolve().is_relative_to(root))
        return found[-1] if found else None
    except Exception:  # noqa: BLE001 - an app whose guide cannot be found simply has none
        return None


def _apps() -> list[dict]:
    out = []
    for a in site_mod.current().installed_apps():
        try:
            h = _hooks(a)
            out.append({"name": a, "title": getattr(h, "app_title", None) or a, "description": getattr(h, "app_description", "") or "", "built_in": a in BUNDLED_APPS,
                        "guide_url": f"/guide/{a}" if guide_file(a) else None})
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

    @app.get("/guide/{app_name}", include_in_schema=False)
    def guide(app_name: str):
        """An installed app's own how-to guide, like /tutorial: one self-contained page, no sign-in needed."""
        f = guide_file(app_name)
        if not f:
            return JSONResponse({"message": "This application has no how-to guide installed."}, status_code=404)
        return FileResponse(f, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

    @app.get("/tutorial", include_in_schema=False)
    @app.get("/tutorial/", include_in_schema=False)
    def tutorial():
        if not TUTORIAL.exists():
            return JSONResponse({"message": "The tutorial file is missing from this installation."}, status_code=404)
        return FileResponse(TUTORIAL, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})
