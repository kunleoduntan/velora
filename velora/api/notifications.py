"""Notification endpoints: my inbox, my preferences, and (for administrators) deliveries, settings, previews.

  GET  /api/notifications?unread=1&limit=&offset=      my inbox + unread count          POST /api/notifications/{name}/read | /api/notifications/read-all
  GET/PUT /api/notification-preferences                my channels, quiet hours, digest, muted rules
  GET  /api/notification-channels                      channels available for rules
  (System Manager)  GET /api/notification-deliveries?status=   POST /api/notification-deliveries/{name}/retry   GET/PUT /api/notification-settings
                    POST /api/notification-settings/test-email   POST /api/notification-rules/preview
"""
from __future__ import annotations

import re

import asyncio
import json

from fastapi import Body, FastAPI, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, select, update

from .. import db, get_list, new_doc, realtime
from ..db.tables import get_table
from ..document.document import now
from ..exceptions import DoesNotExistError, PermissionDenied, ValidationError
from ..meta.registry import registry
from ..permissions import get_session
from ..settings import get_setting, set_setting

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
ENV = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
LOG_FIELDS = ["name", "subject", "message", "ref_doctype", "ref_name", "priority", "rule", "read", "read_on", "creation"]


def _installed():
    if not registry.exists("Notification Log"):
        raise DoesNotExistError("Notifications are not installed on this company. Install the app: velora install-app velora_notify")


def _manager():
    s = get_session()
    if not (s.user == "Administrator" or "System Manager" in s.roles):
        raise PermissionDenied("Only a System Manager can do that")


GATEWAY_TEXT = ("sender", "account_sid", "phone_number_id", "template_name", "template_language", "api_version", "sms_channel", "default_country_code", "format")


def _gateway_settings(key: str, gw, providers) -> dict:
    """Validate and clean an SMS or WhatsApp gateway setting. Secrets are only ever NAMES of environment variables."""
    if not isinstance(gw, dict):
        raise ValidationError(f"{key} must be an object")
    provider = str(gw.get("provider") or "custom").lower()
    if provider not in providers:
        raise ValidationError(f"{key}: provider must be one of {', '.join(providers)}")
    clean: dict = {"provider": provider}
    for f in ("api_key_env", "token_env"):
        if gw.get(f):
            if not ENV.match(str(gw[f])):
                raise ValidationError(f"{f} is the NAME of an environment variable (e.g. SMS_API_KEY), never the key itself")
            clean[f] = gw[f]
    if gw.get("url"):
        if not str(gw["url"]).startswith("https://") and not gw.get("allow_private"):
            raise ValidationError(f"{key}: the gateway address must start with https://")
        clean["url"] = str(gw["url"])
    for f in GATEWAY_TEXT:
        if gw.get(f) not in (None, ""):
            clean[f] = str(gw[f])[:200]
    if clean.get("default_country_code") and not clean["default_country_code"].isdigit():
        raise ValidationError("default_country_code is digits only, for example 234")
    if provider == "custom":
        if not clean.get("url") or not isinstance(gw.get("body"), dict):
            raise ValidationError(f"{key}: a custom gateway needs url and a body (an object using {{to}}, {{message}}, {{sender}} and {{key}})")
        clean["body"] = gw["body"]
        if isinstance(gw.get("headers"), dict):
            clean["headers"] = {str(k)[:60]: str(v)[:300] for k, v in gw["headers"].items()}
    if gw.get("allow_private"):
        clean["allow_private"] = True
    return clean


def install_notification_routes(app: FastAPI, scope, run, workspace=None):
    @app.get("/api/notifications")
    def inbox(request: Request, unread: int = 0, limit: int = 20, offset: int = 0):
        def fn():
            _installed()
            me = get_session().user
            flt = [["user", "=", me]] + ([["read", "=", 0]] if unread else [])
            items = get_list("Notification Log", filters=flt, fields=LOG_FIELDS, order_by="creation desc", limit=min(max(limit, 1), 100), offset=max(offset, 0), ignore_permissions=True)
            t = get_table("Notification Log")
            with db.transaction() as c:
                count = lambda *w: c.execute(select(func.count()).select_from(t).where(t.c.user == me, *w)).scalar()  # noqa: E731
                return {"items": items, "unread": count(t.c.read == 0), "total": count()}
        return run(request, fn)

    @app.post("/api/notifications/read-all")
    def read_all(request: Request):
        def fn():
            _installed()
            t = get_table("Notification Log")
            with db.transaction() as c:
                n = c.execute(update(t).where(t.c.user == get_session().user, t.c.read == 0).values(read=1, read_on=now())).rowcount
            if n:
                realtime.notify(get_session().user, "read")                                          # other open tabs/devices of this user refresh their count
            return {"marked": n}
        return run(request, fn)

    @app.post("/api/notifications/{name}/read")
    def read_one(name: str, request: Request):
        def fn():
            _installed()
            t = get_table("Notification Log")
            with db.transaction() as c:
                n = c.execute(update(t).where(t.c.name == name, t.c.user == get_session().user).values(read=1, read_on=now())).rowcount
            if not n:
                raise DoesNotExistError("Notification not found")                  # someone else's notification looks exactly like a missing one
            realtime.notify(get_session().user, "read")
            return {"read": name}
        return run(request, fn)

    @app.get("/api/events")
    async def events(request: Request):
        """Server-sent events: `event: notification|read|resync` lines (no content: the client refetches through the normal API). A comment line every 15 s keeps proxies open."""
        info = (await run_in_threadpool(run, request, lambda: (_installed(), realtime.describe())[1]))["data"]
        try:
            sub = realtime.HUB.subscribe(info["key"], info["user"], asyncio.get_running_loop(), info["dsn"])
        except OverflowError as e:
            return StreamingResponse(iter([f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"]), status_code=429, media_type="text/event-stream")

        async def stream():
            try:
                yield "retry: 3000\n\nevent: ready\ndata: {}\n\n"
                quiet = 0.0
                while not await request.is_disconnected():                         # a vanished client is noticed within seconds and its slot freed
                    try:
                        msg = await asyncio.wait_for(sub.queue.get(), 3)
                        quiet = 0.0
                    except asyncio.TimeoutError:
                        quiet += 3
                        if quiet >= 15:                                            # a comment line every 15 s keeps proxies from closing an idle stream
                            quiet = 0.0
                            yield ": ping\n\n"
                        continue
                    yield f"event: {msg['kind']}\ndata: {json.dumps(msg)}\n\n"
            finally:
                realtime.HUB.unsubscribe(sub)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/notification-preferences")
    def get_prefs(request: Request):
        def fn():
            _installed()
            r = get_list("Notification Preference", filters=[["user", "=", get_session().user]], fields=["email_enabled", "quiet_start", "quiet_end", "digest", "muted_rules"], limit=1, ignore_permissions=True)
            p = r[0] if r else {"email_enabled": 1, "quiet_start": None, "quiet_end": None, "digest": "Immediately", "muted_rules": ""}
            return {**p, "email_enabled": bool(p["email_enabled"]), "muted_rules": [x for x in (p["muted_rules"] or "").splitlines() if x.strip()]}
        return run(request, fn)

    @app.put("/api/notification-preferences")
    def put_prefs(request: Request, body: dict = Body(...)):
        def fn():
            _installed()
            qs, qe, dg = body.get("quiet_start") or None, body.get("quiet_end") or None, body.get("digest") or "Immediately"
            for v in (qs, qe):
                if v is not None and not (isinstance(v, str) and HHMM.match(v)):
                    raise ValidationError("Quiet hours are HH:MM, e.g. 22:00")
            if (qs is None) != (qe is None):
                raise ValidationError("Give both a start and an end for quiet hours, or neither")
            if dg not in ("Immediately", "Hourly digest", "Daily digest"):
                raise ValidationError("Digest must be Immediately, Hourly digest or Daily digest")
            muted = body.get("muted_rules") or []
            if not isinstance(muted, list) or not all(isinstance(m, str) for m in muted) or len(muted) > 200:
                raise ValidationError("muted_rules must be a list of rule names")
            me = get_session().user
            vals = dict(email_enabled=1 if body.get("email_enabled", True) else 0, quiet_start=qs, quiet_end=qe, digest=dg, muted_rules="\n".join(m.strip() for m in muted if m.strip()))
            existing = get_list("Notification Preference", filters=[["user", "=", me]], fields=["name"], limit=1, ignore_permissions=True)
            if existing:
                from .. import get_doc
                d = get_doc("Notification Preference", me, ignore_permissions=True)
                d.update(vals)
                d.save(ignore_permissions=True)
            else:
                new_doc("Notification Preference", user=me, **vals).insert(ignore_permissions=True)
            return {"saved": True}
        return run(request, fn)

    @app.get("/api/notification-channels")
    def channels_list(request: Request):
        def fn():
            _installed()
            from velora_notify import channels
            return {"channels": channels.names()}
        return run(request, fn)

    # ---------------- administrators ----------------
    @app.get("/api/notification-deliveries")
    def deliveries(request: Request, status: str = "", limit: int = 50):
        def fn():
            _installed()
            _manager()
            from velora_notify import outbox
            flt = [["status", "=", status]] if status else []
            return {"items": get_list("Notification Delivery", filters=flt, fields=["name", "rule", "channel", "recipient", "subject", "status", "attempts", "next_attempt", "last_error", "creation"],
                                      order_by="creation desc", limit=min(max(limit, 1), 200), ignore_permissions=True), "counts": outbox.stats()}
        return run(request, fn)

    @app.post("/api/notification-deliveries/{name}/retry")
    def retry(name: str, request: Request):
        def fn():
            _installed()
            _manager()
            from velora_notify import outbox
            try:
                return outbox.retry(name)
            except ValueError as e:
                raise ValidationError(str(e)) from None
        return run(request, fn)

    @app.get("/api/notification-settings")
    def get_settings(request: Request):
        def fn():
            _installed()
            _manager()
            return get_setting("notify.settings", {}) or {}
        return run(request, fn)

    @app.put("/api/notification-settings")
    def put_settings(request: Request, body: dict = Body(...)):
        def fn():
            _installed()
            _manager()
            out: dict = {}
            em = body.get("email")
            if em:
                if not isinstance(em, dict) or not str(em.get("host", "")).strip() or "@" not in str(em.get("from_addr", "")):
                    raise ValidationError("Email needs a host and a from_addr")
                if em.get("password_env") and not ENV.match(str(em["password_env"])):
                    raise ValidationError("password_env is the NAME of an environment variable (e.g. SMTP_PASSWORD), never the password itself")
                out["email"] = {k: em[k] for k in ("host", "port", "user", "password_env", "from_addr", "starttls", "ssl") if k in em and em[k] not in (None, "")}
            wh = body.get("webhook")
            if wh:
                if wh.get("secret_env") and not ENV.match(str(wh["secret_env"])):
                    raise ValidationError("secret_env is the NAME of an environment variable, never the secret itself")
                out["webhook"] = {k: wh[k] for k in ("allow_http", "allow_private", "secret_env") if k in wh}
            for key, providers in (("sms", ("termii", "twilio", "custom")), ("whatsapp", ("meta", "twilio", "custom"))):
                gw = body.get(key)
                if gw:
                    out[key] = _gateway_settings(key, gw, providers)
            if body.get("base_url"):
                if not str(body["base_url"]).startswith(("https://", "http://")):
                    raise ValidationError("base_url must start with https:// (or http://)")
                out["base_url"] = str(body["base_url"]).rstrip("/")
            set_setting("notify.settings", out)
            return out
        return run(request, fn)

    @app.post("/api/notification-settings/test-email")
    def test_email(request: Request, body: dict = Body(...)):
        def fn():
            _installed()
            _manager()
            from velora_notify import channels
            to = str(body.get("to", "")).strip()
            if not channels.valid_email(to):
                raise ValidationError("Enter a valid email address")
            try:
                channels.send_email({"recipient": to, "subject": "Velora test email", "body": "If you can read this, email notifications are working.", "payload": {}})
            except channels.PermanentError as e:
                raise ValidationError(str(e)) from None
            except Exception as e:  # noqa: BLE001
                raise ValidationError(f"Could not send: {type(e).__name__}: {e}") from None
            return {"sent": to}
        return run(request, fn)

    @app.post("/api/notification-rules/preview")
    def preview(request: Request, body: dict = Body(...)):
        def fn():
            _installed()
            _manager()
            from velora_notify import engine
            if not all(isinstance(body.get(k), str) and body.get(k) for k in ("rule", "doctype", "name")):
                raise ValidationError("rule, doctype and name are required")
            return engine.preview(body["rule"], body["doctype"], body["name"])
        return run(request, fn)
