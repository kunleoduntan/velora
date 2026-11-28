"""Pick the site for each request (pure ASGI middleware, so the choice is visible to every endpoint).

Resolution order: a forced site (`velora start --site X`) → a site directory named like the Host header
(`erp.client-a.com` → sites/erp.client-a.com) → for loopback hosts, the workspace's current site.
"""
from __future__ import annotations

import json
import re

import anyio

from .. import site as site_mod
from ..workspace import Workspace

_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
_LOOPBACK = {"localhost", "127.0.0.1", "::1", "testserver"}


class SiteResolver:
    def __init__(self, ws: Workspace, forced: str | None = None):
        self.ws, self.forced = ws, forced

    def name_for(self, host: str) -> str | None:
        if self.forced:
            return self.forced
        host = host.strip().lower()
        h = host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        if h in _LOOPBACK:                                  # exact match against a fixed set, so safe to test first
            try:
                return self.ws.current_site()
            except Exception:  # noqa: BLE001 - no default site configured
                return None
        valid = bool(_HOST_RE.match(h)) and ".." not in h
        if not valid:
            return None                                     # malformed Host header: never served
        if h in self.ws.sites():                            # exact directory match only: no path tricks
            return h
        default = self.ws.common_config().get("default_site")   # opt-in: e.g. when the server is reached by IP address
        return default if default in self.ws.sites() else None

    def __call__(self, host: str):
        name = self.name_for(host)
        return site_mod.load_site(self.ws.site_path(name)) if name else None


class SiteMiddleware:
    def __init__(self, app, resolver: SiteResolver):
        self.app, self.resolver = app, resolver

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        host = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"host"), "")
        is_api = scope["path"].startswith("/api")
        site, err = None, None
        try:
            site = await anyio.to_thread.run_sync(self.resolver, host)   # first load of a site touches the database
        except Exception as e:  # noqa: BLE001
            err = (503, "SiteUnavailable", f"Site could not be loaded: {str(e).splitlines()[0][:200]}")
        if site is not None and err is None:
            from ..upgrade.state import check_site, gate_message
            try:
                gate, recorded = await anyio.to_thread.run_sync(check_site, site)
                if gate != "ok":
                    err = (503, "UpgradePending", gate_message(gate, recorded))
            except Exception:  # noqa: BLE001 - an unreachable database is reported by the endpoint itself
                pass
        if site is None and err is None and is_api:
            err = (404, "SiteNotFound", f"No site is configured for host {host!r}")
        if err and is_api and scope["type"] == "http":
            body = json.dumps({"error": err[1], "message": err[2], "details": None}).encode()
            await send({"type": "http.response.start", "status": err[0], "headers": [(b"content-type", b"application/json"),
                                                                                       (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        if site is None:
            return await self.app(scope, receive, send)      # static assets need no site
        with site_mod.use(site):
            await self.app(scope, receive, send)
