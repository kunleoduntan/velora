"""Explicit, opt-in operational alert delivery adapters."""
from __future__ import annotations
import json, os, smtplib, ssl
from email.message import EmailMessage
from urllib.parse import urlparse
from urllib.request import Request, urlopen

class DeliveryError(RuntimeError): pass

def send_email(subject: str, body: str, *, recipient: str, sender: str | None = None) -> None:
    host=os.environ.get("VELORA_SMTP_HOST"); port=int(os.environ.get("VELORA_SMTP_PORT", "587"))
    user=os.environ.get("VELORA_SMTP_USER"); password=os.environ.get("VELORA_SMTP_PASSWORD")
    sender=sender or os.environ.get("VELORA_SMTP_FROM")
    if not host or not sender: raise DeliveryError("SMTP host and sender must be configured")
    msg=EmailMessage(); msg["Subject"]=subject; msg["From"]=sender; msg["To"]=recipient; msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo(); smtp.starttls(context=ssl.create_default_context()); smtp.ehlo()
            if user: smtp.login(user, password or "")
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc: raise DeliveryError(f"SMTP delivery failed: {exc}") from exc

def send_webhook(url: str, payload: dict, *, timeout: int = 10) -> int:
    parsed=urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise DeliveryError("Webhook URL must be an HTTPS URL without embedded credentials")
    token=os.environ.get("VELORA_WEBHOOK_TOKEN")
    headers={"Content-Type":"application/json", "User-Agent":"Velora-Operations/0.47"}
    if token: headers["Authorization"]="Bearer "+token
    req=Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as response:
            code=int(response.status)
            if code < 200 or code >= 300: raise DeliveryError(f"Webhook returned HTTP {code}")
            return code
    except Exception as exc:
        if isinstance(exc, DeliveryError): raise
        raise DeliveryError(f"Webhook delivery failed: {exc}") from exc

def deliver_alerts(report: dict, *, email: str | None = None, webhook: str | None = None) -> dict:
    """Deliver active alerts only when destinations are explicitly supplied."""
    alerts=report.get("alerts", [])
    if not alerts: return {"sent": 0, "results": []}
    body="\n".join(f"[{a.get('severity','warning').upper()}] {a.get('code')}: {a.get('message')}" for a in alerts)
    results=[]
    if email:
        send_email("Velora operational alert", body, recipient=email); results.append({"channel":"email","status":"sent"})
    if webhook:
        code=send_webhook(webhook, {"source":"velora","alerts":alerts,"generated_at":report.get("generated_at")})
        results.append({"channel":"webhook","status":"sent","http_status":code})
    return {"sent":len(results),"results":results}
