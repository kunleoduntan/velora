"""Delivery channels. Built in: Email (SMTP), Webhook (signed HTTPS POST). In-App is handled by the engine (it is the inbox).

Add your own from any app:   velora_notify.channels.register("sms", send)   where   send(delivery: dict, settings: dict) -> None
Raise PermanentError for "do not retry" (bad address, rejected); any other exception is retried with backoff."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from html import escape
from urllib.parse import urlparse

from velora.settings import get_setting


from velora import safe_http  # noqa: E402


from .gateways import PermanentError  # noqa: E402  (one class, so a gateway's "do not retry" is understood by the outbox)


CHANNELS: dict[str, object] = {}
EMAIL_RE = re.compile(r"^[^@\s,;<>()\[\]\\\"']+@[^@\s,;<>()\[\]\\\"']+\.[^@\s,;<>()\[\]\\\"']+$")


def register(name: str, send) -> None:
    CHANNELS[name] = send


def names() -> list[str]:
    return ["In-App", "Email", "Webhook"] + [n for n in CHANNELS if n not in ("Email", "Webhook")]


def settings() -> dict:
    return get_setting("notify.settings", {}) or {}


def _secret(env_name: str | None) -> str | None:
    return os.environ.get(env_name) if env_name else None


def valid_email(addr: str) -> bool:
    return bool(addr) and len(addr) <= 254 and "\n" not in addr and "\r" not in addr and bool(EMAIL_RE.match(addr))


def send_email(d: dict, cfg_all: dict | None = None) -> None:
    cfg = (cfg_all if cfg_all is not None else settings()).get("email") or {}
    if not cfg.get("host") or not cfg.get("from_addr"):
        raise PermanentError("Email is not set up: configure notify.settings.email (host, port, from_addr, user, password_env)")
    to = d["recipient"]
    if not valid_email(to):
        raise PermanentError(f"{to!r} is not a valid email address")
    p = d.get("payload") or {}
    cc = [a for a in (p.get("cc") or []) if valid_email(a)]
    bcc = [a for a in (p.get("bcc") or []) if valid_email(a)]
    msg = EmailMessage()
    msg["From"], msg["To"] = (f"{p['from_name']} <{cfg['from_addr']}>" if p.get("from_name") and not re.search(r"[\r\n<>]", p["from_name"]) else cfg["from_addr"]), to
    if cc:
        msg["Cc"] = ", ".join(cc)
    if p.get("reply_to") and valid_email(p["reply_to"]):
        msg["Reply-To"] = p["reply_to"]
    if p.get("unsubscribe_url") and str(p["unsubscribe_url"]).startswith(("https://", "http://")):
        msg["List-Unsubscribe"] = f"<{p['unsubscribe_url']}>"
    msg["Subject"] = re.sub(r"[\r\n]+", " ", d["subject"] or "Notification")[:200]
    msg.set_content(d["body"] or "")
    link = p.get("link")
    html = p.get("html") or ("<p>" + escape(d["body"] or "").replace("\n", "<br>") + "</p>" + (f'<p><a href="{escape(link)}">Open</a></p>' if link else ""))
    msg.add_alternative(html, subtype="html")
    _attach_files(msg, p)
    port = int(cfg.get("port") or (465 if cfg.get("ssl") else 587))
    try:
        if cfg.get("ssl"):
            smtp = smtplib.SMTP_SSL(cfg["host"], port, timeout=20, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(cfg["host"], port, timeout=20)
        with smtp:
            if not cfg.get("ssl") and cfg.get("starttls", True):
                smtp.starttls(context=ssl.create_default_context())
            if cfg.get("user"):
                smtp.login(cfg["user"], _secret(cfg.get("password_env")) or "")
            if cc or bcc:
                smtp.send_message(msg, to_addrs=[to, *cc, *bcc])           # a blind copy is not a header, so the envelope names everyone
            else:
                smtp.send_message(msg)
    except smtplib.SMTPRecipientsRefused as e:
        raise PermanentError(f"The server refused the recipient: {e}") from None
    except smtplib.SMTPResponseException as e:
        if 500 <= e.smtp_code < 600:
            raise PermanentError(f"SMTP {e.smtp_code}: {e.smtp_error!r}") from None
        raise


def _attach_files(msg: EmailMessage, p: dict) -> None:
    """Attachments and inline pictures are stored once, as file ids; each message loads them when it is sent."""
    ids, inline = list(p.get("attachments") or []), list(p.get("inline_images") or [])
    if not ids and not inline:
        return
    from velora import files
    for n, fid in enumerate(inline, 1):
        meta, data = files.get_file(fid)
        kind, _, sub = (meta["content_type"] or "image/png").partition("/")
        html_part = msg.get_body(("html",))
        html_part.add_related(data, maintype=kind, subtype=sub or "png", cid=f"<img{n}>")
    for fid in ids:
        meta, data = files.get_file(fid)
        kind, _, sub = (meta["content_type"] or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=kind, subtype=sub or "octet-stream", filename=meta["file_name"])


def _check_target(host: str, port: int, allow_private: bool) -> tuple[list[str], str | None]:
    """(the addresses it is safe to connect to, or [] and the reason it is not). Every address is validated, IPv6-embedded IPv4 included."""
    try:
        return safe_http.resolve(host, port, allow_private), None
    except safe_http.UnsafeTarget as exc:
        return [], str(exc)


def _blocked(host: str, allow_private: bool) -> str | None:
    return _check_target(host, 443, allow_private)[1]


def send_webhook(d: dict, cfg_all: dict | None = None, opener=None) -> None:
    cfg = (cfg_all if cfg_all is not None else settings()).get("webhook") or {}
    url = d["recipient"]
    u = urlparse(url)
    if u.scheme not in ("https", "http") or not u.hostname:
        raise PermanentError(f"{url!r} is not a valid webhook URL")
    if u.scheme == "http" and not cfg.get("allow_http"):
        raise PermanentError("Webhook URLs must use https (or enable allow_http for testing)")
    ips, why = _check_target(u.hostname, u.port or (443 if u.scheme == "https" else 80), bool(cfg.get("allow_private")))
    if why:
        raise PermanentError(f"Blocked: {why}")
    body = json.dumps({"id": d.get("name"), "rule": d.get("rule"), "subject": d.get("subject"), "message": d.get("body"), "priority": d.get("priority"),
                       "doctype": d.get("ref_doctype"), "name": d.get("ref_name"), **(d.get("payload") or {})}, default=str).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "Velora-Notify/1", "X-Velora-Delivery": str(d.get("name"))}
    secret = _secret(cfg.get("secret_env"))
    if secret:
        headers["X-Velora-Signature"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    import http.client
    if opener is not None:
        conn = opener(u.hostname, u.port, timeout=10)                                   # (a test double)
    else:                                                                               # connect to the address that was just CHECKED, never to a name that may resolve elsewhere now
        pinned = safe_http.PinnedHTTPSConnection if u.scheme == "https" else safe_http.PinnedHTTPConnection
        conn = pinned(u.hostname, u.port, pinned_ip=ips[0], timeout=10)
    try:
        conn.request("POST", (u.path or "/") + (f"?{u.query}" if u.query else ""), body, headers)
        status = conn.getresponse().status
    finally:
        conn.close()
    if status in (408, 425, 429) or status >= 500:
        raise RuntimeError(f"the receiver answered {status}")
    if status >= 400:
        raise PermanentError(f"the receiver rejected it ({status})")


register("Email", send_email)
register("Webhook", send_webhook)
from . import gateways as _gw  # noqa: E402
register("SMS", _gw.send_sms)
register("WhatsApp", _gw.send_whatsapp)
