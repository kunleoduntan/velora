"""Company-local integration services for API credentials, provider adapters and webhooks.

Secrets are shown once, stored only as SHA-256 digests, and never written to integration logs.
Each company's tables live in that company's database.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import urllib.error
import urllib.request
from datetime import timedelta
from typing import Callable
from urllib.parse import urlparse

from . import safe_http

from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, select, update
from cryptography.fernet import Fernet
import os

from . import db
from .document.document import now
from .exceptions import PermissionDenied, ValidationError
from .permissions import get_session

_meta = MetaData()
_keys = Table("vl_api_credential", _meta,
    Column("id", String(32), primary_key=True), Column("label", String(120), nullable=False),
    Column("key_hash", String(64), nullable=False, unique=True), Column("scopes", JSON, nullable=False),
    Column("active", Integer, nullable=False, default=1), Column("expires_on", DateTime),
    Column("last_used", DateTime), Column("created_by", String(140), nullable=False),
    Column("created_on", DateTime, nullable=False), Column("revoked_on", DateTime))
_hooks = Table("vl_webhook_subscription", _meta,
    Column("id", String(32), primary_key=True), Column("label", String(120), nullable=False),
    Column("target_url", Text, nullable=False), Column("events", JSON, nullable=False),
    Column("secret_ciphertext", Text, nullable=False), Column("active", Integer, nullable=False, default=1),
    Column("created_by", String(140), nullable=False), Column("created_on", DateTime, nullable=False))
_logs = Table("vl_integration_log", _meta,
    Column("id", String(32), primary_key=True), Column("integration", String(160), nullable=False),
    Column("direction", String(12), nullable=False), Column("event", String(160)),
    Column("status", String(24), nullable=False), Column("http_status", Integer),
    Column("attempts", Integer, nullable=False, default=0), Column("request_id", String(64)),
    Column("summary", String(500)), Column("created_on", DateTime, nullable=False),
    Column("completed_on", DateTime), Column("next_attempt", DateTime))
_queue = Table("vl_webhook_queue", _meta,
    Column("id", String(32), primary_key=True), Column("subscription_id", String(32), nullable=False),
    Column("event", String(160), nullable=False), Column("payload", JSON, nullable=False),
    Column("status", String(24), nullable=False), Column("attempts", Integer, nullable=False, default=0),
    Column("next_attempt", DateTime, nullable=False), Column("created_on", DateTime, nullable=False),
    Column("claimed_at", DateTime), Column("last_error", String(500)))

PROVIDERS: dict[str, Callable] = {}
BACKOFF = (60, 300, 1800, 7200, 43200)

def ensure():
    from .db import extra_tables; extra_tables.ensure(_meta)

def _manager():
    s = get_session()
    if s.user != "Administrator" and "System Manager" not in s.roles:
        raise PermissionDenied("System Manager permission is required")

def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()

def _fernet():
    key = os.environ.get("VELORA_INTEGRATION_MASTER_KEY") or os.environ.get("VELORA_MASTER_KEY")
    if not key:
        raise ValidationError("Set VELORA_INTEGRATION_MASTER_KEY (a Fernet key) to enable signed webhooks")
    try:
        return Fernet(key.encode())
    except Exception:
        raise ValidationError("VELORA_INTEGRATION_MASTER_KEY must be a valid Fernet key") from None

def issue_api_key(label: str, scopes: list[str], expires_on=None) -> dict:
    _manager(); ensure()
    if not isinstance(label, str) or not label.strip() or len(label) > 120:
        raise ValidationError("A credential label (1–120 characters) is required")
    allowed = {"read", "write", "submit", "reports", "webhooks"}
    if not isinstance(scopes, list) or not scopes or len(scopes) > 10 or not set(scopes) <= allowed:
        raise ValidationError("Scopes must be selected from: " + ", ".join(sorted(allowed)))
    raw = "vla_" + secrets.token_urlsafe(36)
    at = now()
    row = dict(id=secrets.token_hex(16), label=label.strip(), key_hash=_hash(raw), scopes=scopes,
               active=1, expires_on=expires_on, created_by=get_session().user, created_on=at)
    with db.transaction() as c:
        c.execute(_keys.insert().values(**row))
    return {"id": row["id"], "label": row["label"], "api_key": raw, "scopes": scopes,
            "expires_on": expires_on, "warning": "Copy this key now. It cannot be retrieved again."}

def authenticate_api_key(raw: str, required_scope: str = "read") -> dict | None:
    """Validate a company-local API key. Returns credential metadata or None."""
    if not isinstance(raw, str) or not raw.startswith("vla_"):
        return None
    ensure()
    with db.transaction() as c:
        row = c.execute(select(_keys).where(_keys.c.key_hash == _hash(raw), _keys.c.active == 1)).mappings().first()
        if not row:
            return None
        row = dict(row)
        if row["expires_on"] and row["expires_on"] <= now():
            return None
        if required_scope not in row["scopes"]:
            raise PermissionDenied(f"API credential does not have the {required_scope!r} scope")
        c.execute(update(_keys).where(_keys.c.id == row["id"]).values(last_used=now()))
    return {"id": row["id"], "label": row["label"], "scopes": row["scopes"], "created_by": row["created_by"]}

def list_api_keys() -> list[dict]:
    _manager(); ensure()
    with db.transaction() as c:
        rows = c.execute(select(_keys.c.id, _keys.c.label, _keys.c.scopes, _keys.c.active,
                                _keys.c.expires_on, _keys.c.last_used, _keys.c.created_by, _keys.c.created_on,
                                _keys.c.revoked_on).order_by(_keys.c.created_on.desc())).mappings().all()
    return [dict(r) for r in rows]

def revoke_api_key(key_id: str) -> bool:
    _manager(); ensure()
    with db.transaction() as c:
        return c.execute(update(_keys).where(_keys.c.id == key_id, _keys.c.active == 1)
                         .values(active=0, revoked_on=now())).rowcount == 1

def register_provider(channel: str, sender: Callable):
    """Register a provider sender. Signature: sender(recipient, message, config) -> provider response."""
    name = str(channel).strip().upper()
    if name not in {"SMS", "WHATSAPP"} or not callable(sender):
        raise ValueError("Register SMS or WHATSAPP with a callable sender")
    PROVIDERS[name] = sender

def send_message(channel: str, recipient: str, message: str, config: dict | None = None):
    name = str(channel).strip().upper()
    if name not in PROVIDERS:
        raise ValidationError(f"No {name} provider is registered. Install/configure a provider adapter.")
    if not recipient or len(recipient) > 254 or not message or len(message) > 10000:
        raise ValidationError("Recipient and message are required; message limit is 10,000 characters")
    ensure()
    request_id = secrets.token_hex(16)
    try:
        result = PROVIDERS[name](recipient, message, config or {})
    except Exception as exc:
        with db.transaction() as c:
            c.execute(_logs.insert().values(id=secrets.token_hex(16), integration=name, direction="Outbound",
                event="message.send", status="Failed", attempts=1, request_id=request_id,
                summary=f"{type(exc).__name__}: {exc}"[:500], created_on=now(), completed_on=now()))
        raise
    with db.transaction() as c:
        c.execute(_logs.insert().values(id=secrets.token_hex(16), integration=name, direction="Outbound",
            event="message.send", status="Sent", attempts=1, request_id=request_id,
            summary="Provider accepted message", created_on=now(), completed_on=now()))
    return result

def _resolve_target(url: str) -> tuple[str, list[str]]:
    """Validate a webhook URL and return (hostname, the public addresses it may be sent to)."""
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValidationError("Webhook target must be an HTTPS URL on the standard port")
    try:
        return p.hostname, safe_http.resolve(p.hostname, 443)
    except safe_http.UnsafeTarget:
        raise ValidationError("Webhook target must resolve only to public IP addresses") from None

def _public_https(url: str) -> str:
    _resolve_target(url)
    return url

def create_webhook(label: str, target_url: str, events: list[str]) -> dict:
    _manager(); ensure()
    if not isinstance(label, str) or not label.strip() or len(label) > 120:
        raise ValidationError("Webhook label is required (maximum 120 characters)")
    target_url = _public_https(target_url)
    if not isinstance(events, list) or not events or len(events) > 100 or not all(isinstance(x, str) and 0 < len(x) <= 160 for x in events):
        raise ValidationError("Provide 1–100 event names")
    secret = secrets.token_urlsafe(32); ident = secrets.token_hex(16); at = now()
    with db.transaction() as c:
        c.execute(_hooks.insert().values(id=ident, label=label.strip(), target_url=target_url, events=events,
            secret_ciphertext=_fernet().encrypt(secret.encode()).decode(), active=1, created_by=get_session().user, created_on=at))
    return {"id": ident, "label": label.strip(), "secret": secret,
            "warning": "Save this signing secret now. It cannot be retrieved again."}

def enqueue_event(event: str, payload: dict) -> int:
    """Queue matching outgoing webhooks. Call inside/after a successful business transaction."""
    ensure()
    with db.transaction() as c:
        subs = c.execute(select(_hooks.c.id).where(_hooks.c.active == 1)).all()
        # Read event lists individually to retain portability across JSON dialects.
        matched = []
        for (sid,) in subs:
            row = c.execute(select(_hooks.c.events).where(_hooks.c.id == sid)).scalar()
            if "*" in (row or []) or event in (row or []):
                matched.append(sid)
        for sid in matched:
            c.execute(_queue.insert().values(id=secrets.token_hex(16), subscription_id=sid, event=event,
                payload=payload, status="Queued", attempts=0, next_attempt=now(), created_on=now()))
    return len(matched)

def deliver_webhooks(limit: int = 30) -> dict:
    """Deliver due webhooks with HMAC signatures, bounded retries and per-attempt logs."""
    ensure(); stats={"sent":0,"retry":0,"dead":0}
    with db.transaction() as c:
        jobs = c.execute(select(_queue).where(_queue.c.status == "Queued", _queue.c.next_attempt <= now())
                         .order_by(_queue.c.next_attempt).limit(limit)).mappings().all()
    for job in jobs:
        job=dict(job)
        with db.transaction() as c:
            claimed=c.execute(update(_queue).where(_queue.c.id==job["id"],_queue.c.status=="Queued")
                              .values(status="Sending", claimed_at=now())).rowcount
        if not claimed: continue
        with db.transaction() as c:
            sub=c.execute(select(_hooks).where(_hooks.c.id==job["subscription_id"],_hooks.c.active==1)).mappings().first()
        if not sub:
            with db.transaction() as c:
                c.execute(update(_queue).where(_queue.c.id==job["id"]).values(status="Dead",last_error="Webhook subscription inactive"))
            stats["dead"]+=1; continue
        body=json.dumps({"id":job["id"],"event":job["event"],"created_on":job["created_on"].isoformat(),"data":job["payload"]},
                        separators=(",",":"),default=str).encode()
        signing_secret = _fernet().decrypt(sub["secret_ciphertext"].encode())
        signature=hmac.new(signing_secret,body,hashlib.sha256).hexdigest()
        # Re-resolve and re-check immediately before delivery. Redirects are disabled so a
        # public endpoint cannot redirect the worker to an internal service.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise ValidationError("Webhook redirects are not permitted")
        pinned_ip = None
        try:
            _host, addresses = _resolve_target(sub["target_url"])
            pinned_ip = addresses[0]
        except ValidationError:
            pass                                                              # reported below as this attempt's error
        class Pinned(urllib.request.HTTPSHandler):
            """Connect to the address that was just CHECKED, not to a name that could now resolve somewhere else (DNS rebinding)."""
            def https_open(self, req):
                return self.do_open(lambda host, **kw: safe_http.PinnedHTTPSConnection(host, pinned_ip=pinned_ip, **kw), req, context=self._context)
        opener = urllib.request.build_opener(NoRedirect, Pinned)
        req=urllib.request.Request(sub["target_url"],data=body,headers={"Content-Type":"application/json",
            "X-Velora-Event":job["event"],"X-Velora-Delivery":job["id"],"X-Velora-Signature":"sha256="+signature},method="POST")
        err=None; status=None
        try:
            if pinned_ip is None:
                _resolve_target(sub["target_url"])                          # raises the reason (not HTTPS, or not a public address)
            with opener.open(req,timeout=10) as response:
                status=response.status
                if status < 200 or status >= 300: raise RuntimeError(f"HTTP {status}")
            final="Sent"; stats["sent"]+=1; nxt=None
        except Exception as e:
            n=job["attempts"]+1
            err=f"{type(e).__name__}: {e}"[:500]
            if n >= len(BACKOFF): final="Dead"; stats["dead"]+=1; nxt=None
            else: final="Queued"; stats["retry"]+=1; nxt=now()+timedelta(seconds=BACKOFF[n-1])
        with db.transaction() as c:
            c.execute(update(_queue).where(_queue.c.id==job["id"]).values(status=final,attempts=job["attempts"]+(1 if err else 0),
                next_attempt=nxt or job["next_attempt"],claimed_at=None,last_error=err))
            c.execute(_logs.insert().values(id=secrets.token_hex(16),integration=sub["label"],direction="Outbound",
                event=job["event"],status=final,http_status=status,attempts=job["attempts"]+(1 if err else 0),
                request_id=job["id"],summary=err or "Webhook delivered",created_on=now(),completed_on=now() if final=="Sent" else None))
    return stats

def integration_logs(limit: int = 100) -> list[dict]:
    _manager(); ensure()
    with db.transaction() as c:
        rows=c.execute(select(_logs).order_by(_logs.c.created_on.desc()).limit(min(max(int(limit),1),500))).mappings().all()
    return [dict(r) for r in rows]


def deactivate_webhook(subscription_id: str) -> bool:
    _manager(); ensure()
    with db.transaction() as c:
        return c.execute(update(_hooks).where(_hooks.c.id == subscription_id, _hooks.c.active == 1)
                         .values(active=0)).rowcount == 1

def retry_webhook(delivery_id: str) -> bool:
    _manager(); ensure()
    with db.transaction() as c:
        return c.execute(update(_queue).where(_queue.c.id == delivery_id, _queue.c.status == "Dead")
                         .values(status="Queued", attempts=0, next_attempt=now(), claimed_at=None, last_error=None)).rowcount == 1

def recover_stuck_webhooks(at=None) -> int:
    """Recover queue rows left Sending by a worker crash."""
    at = at or now()
    from datetime import timedelta
    cutoff = at - timedelta(minutes=10)
    with db.transaction() as c:
        dead = c.execute(update(_queue).where(_queue.c.status == "Sending", _queue.c.claimed_at <= cutoff,
            _queue.c.attempts + 1 >= len(BACKOFF)).values(status="Dead", attempts=_queue.c.attempts + 1,
            claimed_at=None, last_error="worker stopped during delivery too many times")).rowcount
        queued = c.execute(update(_queue).where(_queue.c.status == "Sending", _queue.c.claimed_at <= cutoff)
            .values(status="Queued", attempts=_queue.c.attempts + 1, next_attempt=at, claimed_at=None,
                    last_error="worker stopped during delivery; retrying")).rowcount
    return dead + queued
