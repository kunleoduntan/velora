"""Maintenance mode: while an upgrade runs, every API call answers 503 (with Retry-After) and the Desk shows a friendly
"upgrading" screen that retries by itself. Static assets and /api/health still respond, so load balancers and the Desk keep working."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MESSAGE = "Velora is being upgraded. This page will reload by itself when it is ready."
EXEMPT = ("/api/theme/public", "/api/auth/config")


def _flag(ws) -> Path:
    return ws.sites_dir / ".maintenance.json"


def enable(ws, message: str = DEFAULT_MESSAGE, owner: str = "upgrade") -> None:
    ws.sites_dir.mkdir(parents=True, exist_ok=True)
    tmp = _flag(ws).with_suffix(".tmp")
    tmp.write_text(json.dumps({"message": message, "owner": owner, "since": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pid": os.getpid()}))
    os.replace(tmp, _flag(ws))


def disable(ws) -> None:
    _flag(ws).unlink(missing_ok=True)


def status(ws) -> dict | None:
    try:
        return json.loads(_flag(ws).read_text())
    except (OSError, ValueError):
        return None


class MaintenanceMiddleware:
    """Pure ASGI. `blockers` are callables returning None or (error_name, message) - e.g. "the platform database needs an upgrade"."""

    def __init__(self, app, ws, blockers=()):
        self.app, self.ws, self.blockers = app, ws, list(blockers)
        self._cache: tuple[float, dict | None] = (0.0, None)

    def _maintenance(self) -> dict | None:
        now = time.monotonic()
        if now - self._cache[0] > 1.0:                      # one stat() per second, not per request
            self._cache = (now, status(self.ws))
        return self._cache[1]

    def _blocked(self):
        m = self._maintenance()
        if m:
            return "Maintenance", m.get("message", DEFAULT_MESSAGE)
        for b in self.blockers:
            try:
                r = b()
            except Exception:  # noqa: BLE001 - a failing check must not take the server down
                r = None
            if r:
                return r
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api"):
            return await self.app(scope, receive, send)
        blocked = self._blocked()
        path = scope["path"]
        if path == "/api/health":
            from .versions import code_version
            body = {"status": "maintenance" if blocked else "ok", "version": code_version(), **({"message": blocked[1]} if blocked else {})}
            return await self._send(send, 503 if blocked else 200, body, blocked is not None)
        if blocked and path not in EXEMPT:
            return await self._send(send, 503, {"error": blocked[0], "message": blocked[1], "details": None}, True)
        await self.app(scope, receive, send)

    @staticmethod
    async def _send(send, status_code, body, retry):
        raw = json.dumps(body).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()), (b"cache-control", b"no-store")]
        if retry:
            headers.append((b"retry-after", b"15"))
        await send({"type": "http.response.start", "status": status_code, "headers": headers})
        await send({"type": "http.response.body", "body": raw})
