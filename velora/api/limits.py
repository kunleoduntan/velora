"""Request size limits. Without them anyone who can reach the server (even without signing in) can send a multi-gigabyte body and exhaust its memory: the framework reads
bodies into memory, and the only limit used to be an optional nginx setting that `velora start` does not have.

Counted as the bytes ARRIVE, so a chunked upload with no Content-Length cannot slip past, and an honest oversized Content-Length is refused without reading anything.
"""
from __future__ import annotations

import json
import os

DEFAULT_MB = 8                                  # every ordinary API call: JSON is small
UPLOAD_PATHS = {"/api/files": 26, "/api/data-import": 11, "/api/filemanager/upload": 101, "/api/publish-upload": 201}        # attachments (25 MB cap) and data imports (10 MB cap), plus envelope overhead
BODY_METHODS = {"POST", "PUT", "PATCH"}


def limit_for(path: str, default_mb: float | None = None) -> int:
    mb = default_mb if default_mb is not None else float(os.environ.get("VELORA_MAX_BODY_MB") or DEFAULT_MB)
    for prefix, upload_mb in UPLOAD_PATHS.items():
        if path == prefix or path.startswith(prefix + "/"):
            mb = max(mb, upload_mb)
    return int(mb * 1024 * 1024)


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app, default_mb: float | None = None):
        self.app, self.default_mb = app, default_mb

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and ("\x00" in scope.get("path", "") or b"%00" in scope.get("query_string", b"").lower()):
            return await self._refuse(send, 0, status=400, text="The address contains an invalid character (a NUL byte)")      # PostgreSQL cannot store one, and no valid name contains one
        if scope["type"] != "http" or scope["method"] not in BODY_METHODS:
            return await self.app(scope, receive, send)
        limit = limit_for(scope.get("path", ""), self.default_mb)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        try:
            if declared is not None and int(declared) > limit:
                return await self._refuse(send, limit)
        except ValueError:
            return await self._refuse(send, limit, status=400, text="Invalid Content-Length header")
        seen, started, overflowed = 0, False, False

        async def counted_receive():
            nonlocal seen, overflowed
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    overflowed = True
                    raise _TooLarge()
            return message

        async def tracked_send(message):
            nonlocal started
            if overflowed:
                return                                  # FastAPI turns ANY error while reading a body into its own 400: whatever the app says now is not the truth, so drop it
            if message["type"] == "http.response.start":
                started = True
            await send(message)
        try:
            await self.app(scope, counted_receive, tracked_send)
        except _TooLarge:
            pass
        if overflowed and not started:
            await self._refuse(send, limit)
        elif overflowed:
            raise _TooLarge()                           # the response was already streaming: nothing safe can be added

    @staticmethod
    async def _refuse(send, limit, status=413, text=None):
        mb = limit / 1024 / 1024
        body = json.dumps({"error": "PayloadTooLarge" if status == 413 else "BadRequest",
                           "message": text or f"The request is larger than the {mb:g} MB allowed here.", "details": None}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})
