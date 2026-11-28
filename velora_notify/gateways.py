"""SMS and WhatsApp senders. Both talk to an HTTPS gateway that the company configures in `notify.settings`:

    "sms":      {"provider": "termii" | "twilio" | "custom", "api_key_env": "SMS_KEY", "sender": "VALUEIMPACT", "default_country_code": "234", ...}
    "whatsapp": {"provider": "meta" | "twilio" | "custom", "token_env": "WA_TOKEN", "phone_number_id": "123", "template_name": "optional", ...}

Secrets are never stored in settings: they are read from the environment variable named by `*_env`.
Provider request formats are built from each provider's public documentation and have NOT been exercised against the live services from this build; run Test send first.
"""
from __future__ import annotations

import base64
import json
import os
import re
from urllib.parse import urlencode, urlparse

from velora import safe_http

PHONE_CHANNELS = ("SMS", "WhatsApp")


class PermanentError(Exception):
    """Do not retry: the message can never be delivered as it is."""


def normalize_phone(raw, country_code: str = "234") -> str | None:
    """International digits without '+', or None. 0803 123 4567 -> 2348031234567 (Nigeria by default)."""
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        digits = digits[2:]
    elif text.startswith("+"):
        pass
    elif digits.startswith("0") and country_code:
        digits = country_code + digits[1:]
    elif country_code and len(digits) == 10 and not digits.startswith(country_code):
        digits = country_code + digits                                  # 8031234567: the national number without its leading zero
    return digits if 8 <= len(digits) <= 15 else None


def _env(name):
    return os.environ.get(name) if name else None


def _connect(host, port, https, pinned_ip, timeout=15):
    cls = safe_http.PinnedHTTPSConnection if https else safe_http.PinnedHTTPConnection
    return cls(host, port, pinned_ip=pinned_ip, timeout=timeout)


def post(url: str, headers: dict, body: bytes, allow_private: bool = False) -> tuple[int, str]:
    u = urlparse(url)
    if u.scheme != "https" and not allow_private:
        raise PermanentError("The gateway address must use https")
    if not u.hostname:
        raise PermanentError(f"{url!r} is not a valid gateway address")
    https = u.scheme == "https"
    port = u.port or (443 if https else 80)
    try:
        ips = safe_http.resolve(u.hostname, port, allow_private)
    except safe_http.UnsafeTarget as exc:
        raise PermanentError(f"Blocked: {exc}") from None
    conn = _connect(u.hostname, port, https, ips[0])
    try:
        conn.request("POST", (u.path or "/") + (f"?{u.query}" if u.query else ""), body, headers)
        res = conn.getresponse()
        return res.status, res.read(4000).decode("utf-8", "replace")
    finally:
        conn.close()


def _judge(status: int, text: str, what: str):
    if status in (408, 425, 429) or status >= 500:
        raise RuntimeError(f"{what} answered {status}")
    if status >= 400:
        raise PermanentError(f"{what} rejected the message ({status}): {text[:200]}")


def _fill(template, values: dict):
    """Replace {to} {message} {sender} in every string of a JSON-like structure."""
    if isinstance(template, str):
        for k, v in values.items():
            template = template.replace("{" + k + "}", str(v))
        return template
    if isinstance(template, dict):
        return {k: _fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, values) for v in template]
    return template


def _request(channel: str, cfg: dict, to: str, message: str) -> tuple[str, dict, bytes]:
    """(url, headers, body) for the configured provider."""
    provider = (cfg.get("provider") or "custom").lower()
    sender = cfg.get("sender") or ""
    secret = _env(cfg.get("api_key_env") or cfg.get("token_env"))
    if provider == "termii" and channel == "SMS":
        if not secret:
            raise PermanentError("SMS is not set up: the Termii key is missing (api_key_env)")
        body = {"to": to, "from": sender, "sms": message, "type": "plain", "channel": cfg.get("sms_channel") or "generic", "api_key": secret}
        return (cfg.get("url") or "https://api.ng.termii.com/api/sms/send"), {"Content-Type": "application/json"}, json.dumps(body).encode()
    if provider == "twilio":
        sid, token = cfg.get("account_sid"), secret
        if not sid or not token:
            raise PermanentError(f"{channel} is not set up: Twilio needs account_sid and a token (api_key_env)")
        prefix = "whatsapp:" if channel == "WhatsApp" else ""
        form = {"To": f"{prefix}+{to}", "From": f"{prefix}{sender}", "Body": message}
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        return (cfg.get("url") or f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"), {"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {auth}"}, urlencode(form).encode()
    if provider == "meta" and channel == "WhatsApp":
        phone_id = cfg.get("phone_number_id")
        if not phone_id or not secret:
            raise PermanentError("WhatsApp is not set up: phone_number_id and the access token (token_env) are required")
        if cfg.get("template_name"):
            payload = {"messaging_product": "whatsapp", "to": to, "type": "template",
                       "template": {"name": cfg["template_name"], "language": {"code": cfg.get("template_language") or "en"}, "components": [{"type": "body", "parameters": [{"type": "text", "text": message[:1000]}]}]}}
        else:
            payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message[:4096]}}
        return (cfg.get("url") or f"https://graph.facebook.com/{cfg.get('api_version') or 'v19.0'}/{phone_id}/messages"), {"Content-Type": "application/json", "Authorization": f"Bearer {secret}"}, json.dumps(payload).encode()
    if provider == "custom":
        if not cfg.get("url") or not cfg.get("body"):
            raise PermanentError(f"{channel} is not set up: a custom gateway needs url and body")
        values = {"to": to, "message": message, "sender": sender, "key": secret or ""}
        body = _fill(cfg["body"], values)
        headers = {str(k): str(_fill(v, values)) for k, v in (cfg.get("headers") or {}).items()}
        if (cfg.get("format") or "json") == "form":
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            return cfg["url"], headers, urlencode(body).encode()
        headers.setdefault("Content-Type", "application/json")
        return cfg["url"], headers, json.dumps(body).encode()
    raise PermanentError(f"{channel} is not set up: provider {provider!r} is not supported for it")


def _sender(channel: str):
    key = "sms" if channel == "SMS" else "whatsapp"

    def send(d: dict, cfg_all: dict | None = None) -> None:
        from . import channels
        cfg = (cfg_all if cfg_all is not None else channels.settings()).get(key) or {}
        if not cfg:
            raise PermanentError(f"{channel} is not set up: add notify.settings.{key}")
        to = normalize_phone(d.get("recipient"), cfg.get("default_country_code") or "234")
        if not to:
            raise PermanentError(f"{d.get('recipient')!r} is not a valid phone number")
        message = (d.get("body") or d.get("subject") or "").strip()
        if not message:
            raise PermanentError("The message is empty")
        url, headers, body = _request(channel, cfg, to, message)
        status, text = post(url, headers, body, bool(cfg.get("allow_private")))
        _judge(status, text, f"The {channel} gateway")
    return send


send_sms, send_whatsapp = _sender("SMS"), _sender("WhatsApp")
