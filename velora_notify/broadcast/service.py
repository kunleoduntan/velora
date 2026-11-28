"""Broadcast Centre: audience building, personalised sending through the notification outbox, delivery tracking, opt-outs and test sends."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from html import escape

from sqlalchemy import update

from velora import db, get_doc, get_list, throw
from velora.db.tables import get_table
from velora.document.document import now
from velora.meta.registry import registry
from velora.settings import get_setting, set_setting

from velora_notify import channels, engine, gateways, templating

def _in_transaction(fn):
    """Run the whole operation in one transaction (joining the caller's when there is one)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **k):
        with db.transaction():
            return fn(*a, **k)
    return wrapper


ROW_FIELDS = ("full_name", "salutation", "email", "phone", "status", "detail", "source_name")
DONE = ("Sent", "Partly Sent", "Cancelled")


# ---- addresses and opt-outs ---------------------------------------------------------------------------------------------
def clean_address(value, channel: str):
    """The address as it will be used and compared, or None when it cannot receive that channel."""
    if value in (None, ""):
        return None
    if channel == "Email":
        v = str(value).strip().lower()
        return v if channels.valid_email(v) else None
    return gateways.normalize_phone(value, (channels.settings().get("sms" if channel == "SMS" else "whatsapp") or {}).get("default_country_code") or "234")


def opted_out(address: str, channel: str) -> bool:
    rows = get_list("Communication Opt-Out", filters=[["address", "=", address]], fields=["channel"], limit=20, ignore_permissions=True)
    return any(r["channel"] in ("All channels", channel) for r in rows)


def _opt_out_index() -> dict[str, set]:
    index: dict[str, set] = {}
    for r in get_list("Communication Opt-Out", fields=["address", "channel"], limit=500000, ignore_permissions=True):
        index.setdefault(r["address"], set()).add(r["channel"])
    return index


def record_opt_out(address: str, channel: str = "All channels", source: str = "Unsubscribe link", reason: str = ""):
    from velora import new_doc
    for r in get_list("Communication Opt-Out", filters=[["address", "=", address], ["channel", "in", [channel, "All channels"]]], fields=["name"], limit=1, ignore_permissions=True):
        return r["name"]
    return new_doc("Communication Opt-Out", address=address, channel=channel, source=source, reason=reason).insert(ignore_permissions=True).name


# ---- unsubscribe links ---------------------------------------------------------------------------------------------------
def _key() -> bytes:
    k = get_setting("notify.unsubscribe_key")
    if not k:
        k = secrets.token_hex(32)
        set_setting("notify.unsubscribe_key", k)
    return k.encode()


def unsubscribe_token(address: str, channel: str) -> str:
    body = base64.urlsafe_b64encode(f"{channel}|{address}".encode()).decode().rstrip("=")
    return f"{body}.{hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()[:32]}"


def read_token(token: str):
    try:
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()[:32]):
            return None
        channel, address = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode().split("|", 1)
        return (channel, address) if channel in ("Email", "SMS", "WhatsApp") else None
    except Exception:  # noqa: BLE001
        return None


def unsubscribe_url(address: str, channel: str) -> str:
    base = (channels.settings().get("base_url") or "").rstrip("/")
    return f"{base}/api/public/actions/unsubscribe?t={unsubscribe_token(address, channel)}" if base else ""


def unsubscribe_page(params: dict, method: str) -> str:
    """Public page behind every unsubscribe link. Opening the link only asks; the button records it (so a mail scanner opening links cannot unsubscribe anyone)."""
    page = lambda text: f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Unsubscribe</title><body style='font-family:system-ui,sans-serif;max-width:30rem;margin:4rem auto;padding:0 1rem'>{text}</body>"
    parsed = read_token(params.get("t", ""))
    if not parsed:
        return page("<h2>This link is not valid</h2><p>It may have been copied incorrectly.</p>")
    channel, address = parsed
    if method == "POST":
        record_opt_out(address, channel, "Unsubscribe link")
        return page(f"<h2>You have been unsubscribed</h2><p>{escape(address)} will no longer receive these messages.</p>")
    return page(f"<h2>Stop messages to {escape(address)}?</h2><form method=post action='?t={escape(params['t'])}'><button style='padding:.6rem 1.2rem;font-size:1rem'>Unsubscribe</button></form>")


# ---- audience -------------------------------------------------------------------------------------------------------------
def _filters(doc):
    raw = doc.source_filters
    if raw in (None, "", []):
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            throw("The filters must be a valid list such as [[\"status\",\"=\",\"Active\"]].")
    if not isinstance(raw, list):
        throw("The filters must be a list such as [[\"status\",\"=\",\"Active\"]].")
    return raw


def audience_from_records(doc) -> list[dict]:
    dt = (doc.source_doctype or "").strip()
    if not registry.exists(dt):
        throw(f"{dt!r} is not a document type.")
    meta = registry.get(dt)
    columns = set(meta.column_names())
    want = {"name_field": doc.name_field, "email_field": doc.email_field, "phone_field": doc.phone_field, "salutation_field": doc.salutation_field}
    for label, f in want.items():
        if f and f not in columns:
            throw(f"{dt} has no field called {f!r} ({label.replace('_', ' ')}).")
    needed = doc.email_field if doc.channel == "Email" else doc.phone_field
    if not needed:
        throw(f"Say which field holds the {'email address' if doc.channel == 'Email' else 'phone number'}.")
    fields = list(dict.fromkeys(["name", *[f for f in want.values() if f]]))
    rows = get_list(dt, filters=_filters(doc), fields=fields, limit=200000)             # the sender's own read permission applies
    return [{"full_name": r.get(doc.name_field) if doc.name_field else r["name"], "salutation": r.get(doc.salutation_field) if doc.salutation_field else None,
             "email": r.get(doc.email_field) if doc.email_field else None, "phone": r.get(doc.phone_field) if doc.phone_field else None, "source_name": r["name"]} for r in rows]


@_in_transaction
def build_recipients(name: str) -> dict:
    doc = get_doc("Broadcast", name)
    if doc.status in DONE or doc.status == "Sending":
        throw("This broadcast has already been sent.")
    typed = [{f: r.get(f) for f in ROW_FIELDS} for r in doc.recipients if not r.source_name]
    found = audience_from_records(doc) if doc.audience_source != "A typed list" else []
    out, seen = [], set()
    index = _opt_out_index()
    for row in [*typed, *found]:
        row = {**{f: None for f in ROW_FIELDS}, **row, "status": "Pending", "detail": None}
        addr = clean_address(row["email"] if doc.channel == "Email" else row["phone"], doc.channel)
        if addr is None:
            row["status"], row["detail"] = "Skipped", f"No valid {'email address' if doc.channel == 'Email' else 'phone number'}"
        elif addr in seen:
            row["status"], row["detail"] = "Skipped", "Duplicate of an earlier recipient"
        elif index.get(addr, set()) & {"All channels", doc.channel}:
            row["status"], row["detail"] = "Opted out", "On the opt-out list"
        if addr is not None:
            seen.add(addr)
        out.append(row)
    doc.set("recipients", out)
    _counts(doc)
    doc.save()
    return {"recipients": len(out), "will_send": sum(1 for r in out if r["status"] == "Pending"), "skipped": sum(1 for r in out if r["status"] == "Skipped"), "opted_out": sum(1 for r in out if r["status"] == "Opted out")}


def _counts(doc):
    c = {"Pending": 0, "Queued": 0, "Sent": 0, "Failed": 0, "Skipped": 0, "Opted out": 0}
    for r in doc.recipients:
        c[r.status or "Pending"] = c.get(r.status or "Pending", 0) + 1
    doc.total_recipients, doc.queued_count, doc.sent_count = len(doc.recipients), c["Queued"] + c["Pending"], c["Sent"]
    doc.failed_count, doc.skipped_count, doc.opted_out_count = c["Failed"], c["Skipped"], c["Opted out"]


# ---- rendering ------------------------------------------------------------------------------------------------------------
def _context(doc, row: dict | None) -> dict:
    addr = clean_address((row or {}).get("email" if doc.channel == "Email" else "phone"), doc.channel) if row else None
    return {"full_name": (row or {}).get("full_name") or "Valued Customer", "salutation": (row or {}).get("salutation") or "Dear", "sender_name": doc.sender_name or "",
            "video_url": doc.video_url or "#", "unsubscribe_url": unsubscribe_url(addr, doc.channel) if addr else "#"}


def _files(doc):
    """(attachment ids, inline picture ids) for an email. Pictures appear inside an HTML message; everything else is attached."""
    if doc.channel != "Email" or not int(doc.include_attachments or 0):
        return [], []
    from velora import files
    attach, inline = [], []
    for f in files.list_attachments("Broadcast", doc.name):
        (inline if doc.message_is_html and str(f.get("content_type") or "").startswith("image/") else attach).append(f["id"])
    return attach, inline


def render(doc, row: dict | None, test: bool = False) -> dict:
    ctx = _context(doc, row)
    html = bool(int(doc.message_is_html or 0)) and doc.channel == "Email"
    body = templating.render(doc.message, ctx, html=html, limit=templating.MAX_BROADCAST, cap=templating.MAX_BROADCAST)
    subject = templating.render(doc.subject or "", ctx).strip()[:200] if doc.channel == "Email" else ""
    if test and subject:
        subject += " (Test)"
    attach, inline = _files(doc)
    if html and inline:
        body += "".join(f"<p style='text-align:center;margin:15px 0'><img src='cid:img{n}' alt='' style='max-width:100%;height:auto;border-radius:6px'></p>" for n, _ in enumerate(inline, 1))
    payload = {}
    if doc.channel == "Email":
        payload = {"from_name": doc.sender_name or None, "reply_to": doc.reply_to or None, "unsubscribe_url": ctx["unsubscribe_url"] if ctx["unsubscribe_url"] != "#" else None,
                   "cc": _list(doc.cc), "bcc": _list(doc.bcc), "attachments": attach, "inline_images": inline}
        if html:
            payload["html"] = body
        payload = {k: v for k, v in payload.items() if v}
    return {"subject": subject, "body": templating.plain_text(body) if html else body, "payload": payload}


def _list(value) -> list[str]:
    return [a.strip().lower() for a in str(value or "").replace(";", ",").split(",") if a.strip()]


def preview(name: str) -> dict:
    doc = get_doc("Broadcast", name)
    row = next(({f: r.get(f) for f in ROW_FIELDS} for r in doc.recipients if r.status in ("Pending", None)), {"full_name": "Sample Person", "salutation": "Dear"})
    out = render(doc, row)
    return {**out, "html": out["payload"].get("html"), "recipient": row.get("full_name")}


# ---- sending --------------------------------------------------------------------------------------------------------------
def check_ready(doc):
    if doc.channel == "Email" and not (doc.subject or "").strip():
        throw("Write a subject first.")
    if not (doc.message or "").strip():
        throw("Write the message first.")
    for label, src in (("subject", doc.subject), ("message", doc.message)):
        try:
            templating.validate(src or "", templating.MAX_BROADCAST)
        except templating.TemplateError as exc:
            throw(f"The {label}: {exc}")


@_in_transaction
def send(name: str, at=None) -> dict:
    """Send now, or schedule when `at` (naive UTC) is given."""
    doc = get_doc("Broadcast", name)
    if doc.status in DONE or doc.status == "Sending":
        throw("This broadcast has already been sent.")
    check_ready(doc)
    if not any(r.status == "Pending" for r in doc.recipients):
        build_recipients(name)
        doc = get_doc("Broadcast", name)
    pending = [r for r in doc.recipients if r.status == "Pending"]
    if not pending:
        throw("There is nobody to send to. Add recipients, or check the audience.")
    if at is not None:
        if at <= now():
            throw("Choose a time in the future, or press Send now.")
        doc.status, doc.scheduled_for = "Scheduled", at
        doc.save()
        return {"status": "Scheduled", "scheduled_for": at.isoformat(), "recipients": len(pending)}
    rate = max(1, int(doc.send_rate_per_minute or 120))
    start, made = now(), 0
    index = _opt_out_index()
    for i, r in enumerate(pending):
        addr = clean_address(r.email if doc.channel == "Email" else r.phone, doc.channel)
        if addr is None:
            r.status, r.detail = "Skipped", "No valid address"
            continue
        if index.get(addr, set()) & {"All channels", doc.channel}:
            r.status, r.detail = "Opted out", "On the opt-out list"
            continue
        msg = render(doc, {f: r.get(f) for f in ROW_FIELDS})
        ok = engine._insert("Notification Delivery", dict(rule="(broadcast)", channel=doc.channel, recipient=addr, user=None, subject=msg["subject"], body=msg["body"], status="Queued", attempts=0,
                                                           next_attempt=start + timedelta(minutes=i // rate), idempotency_key=engine._key("bc", doc.name, doc.channel, addr),
                                                           ref_doctype="Broadcast", ref_name=doc.name, payload=msg["payload"], priority="Low"))
        r.status, r.detail = ("Queued", None) if ok else ("Skipped", "Already sent in this broadcast")
        made += 1 if ok else 0
    doc.status, doc.started_on, doc.scheduled_for = ("Sending" if made else "Cancelled"), start, None
    _counts(doc)
    doc.save()
    if not made:
        doc.status = "Cancelled"
    return {"status": doc.status, "queued": made}


@_in_transaction
def sync(name: str) -> dict:
    """Bring each recipient's status and the totals up to date from the outbox."""
    doc = get_doc("Broadcast", name)
    sent = {}
    for d in get_list("Notification Delivery", filters=[["ref_doctype", "=", "Broadcast"], ["ref_name", "=", name]], fields=["recipient", "status", "last_error"], limit=500000, ignore_permissions=True):
        sent[d["recipient"]] = d
    changed = False
    for r in doc.recipients:
        if r.status not in ("Queued",):
            continue
        d = sent.get(clean_address(r.email if doc.channel == "Email" else r.phone, doc.channel))
        if not d:
            continue
        new = {"Sent": "Sent", "Dead": "Failed", "Skipped": "Skipped"}.get(d["status"], "Queued")
        if new != r.status:
            r.status, r.detail, changed = new, (d.get("last_error") or None) if new != "Sent" else None, True
    if changed or doc.status == "Sending":
        _counts(doc)
        if doc.status == "Sending" and not any(r.status == "Queued" for r in doc.recipients):
            doc.status = "Partly Sent" if doc.failed_count else "Sent"
            doc.finished_on = now()
        doc.save()
    return {"status": doc.status, "sent": doc.sent_count, "failed": doc.failed_count, "waiting": doc.queued_count}


@_in_transaction
def cancel(name: str) -> dict:
    doc = get_doc("Broadcast", name)
    if doc.status in ("Sent", "Partly Sent", "Cancelled"):
        throw("This broadcast is already finished.")
    t = get_table("Notification Delivery")
    with db.transaction() as c:
        stopped = c.execute(update(t).where(t.c.ref_doctype == "Broadcast", t.c.ref_name == name, t.c.status.in_(["Queued", "Held"])).values(status="Skipped", last_error="Broadcast cancelled")).rowcount
    for r in doc.recipients:
        if r.status in ("Queued", "Pending"):
            r.status, r.detail = "Skipped", "Broadcast cancelled"
    doc.status, doc.finished_on = "Cancelled", now()
    _counts(doc)
    doc.save()
    return {"stopped": stopped}


def send_test(name: str, to: str) -> dict:
    """Send one test message straight away, to one address, and report what really happened (no outbox, no counting)."""
    doc = get_doc("Broadcast", name)
    check_ready(doc)
    addr = clean_address(to, doc.channel)
    if addr is None:
        throw(f"{to!r} is not a valid {'email address' if doc.channel == 'Email' else 'phone number'}.")
    msg = render(doc, {"full_name": "Test Recipient", "salutation": "Dear", **({"email": addr} if doc.channel == "Email" else {"phone": addr})}, test=True)
    return deliver_now(doc.channel, addr, msg["subject"], msg["body"], msg["payload"], ref=("Broadcast", name))


def deliver_now(channel: str, address: str, subject: str, body: str, payload: dict | None = None, ref=("", "")) -> dict:
    sender = channels.CHANNELS.get(channel)
    if sender is None:
        return {"sent": False, "error": f"No sender is registered for {channel}."}
    try:
        sender({"name": "test", "channel": channel, "recipient": address, "subject": subject, "body": body, "payload": payload or {}, "rule": "(test)",
                "ref_doctype": ref[0], "ref_name": ref[1], "priority": "Normal"}, channels.settings())
        return {"sent": True, "to": address}
    except Exception as exc:  # noqa: BLE001 - the whole point is to show the person why it failed
        return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}


def test_rule(rule_name: str, doc_name: str, to: str) -> dict:
    """Render a notification rule for a real document and send it to one address now, so the wording and the channel setup can be checked."""
    rule = get_doc("Notification Rule", rule_name)
    target = get_doc(rule.ref_doctype, doc_name)
    ctx = {"doc": engine.expr.DocView(target.as_dict()), "old": engine.expr.DocView(None), "event": "Test", "user": engine.get_session().user, "rule": rule.name, "link": engine._link(target)}
    subject = templating.render(rule.subject, ctx).strip()[:200]
    html = rule.message_format == "HTML"
    text = templating.render(rule.message, ctx, html=html, limit=templating.MAX_BROADCAST, cap=templating.MAX_BROADCAST)
    out = []
    for ch in rule.channels:
        channel = ch.channel
        if channel in ("In-App", "Webhook"):
            continue
        address = clean_address(to, channel) or None
        if address is None:
            out.append({"channel": channel, "sent": False, "error": f"{to!r} is not a valid address for {channel}"})
            continue
        payload = {"link": ctx["link"], **({"html": text} if html and channel == "Email" else {})}
        out.append({"channel": channel, **deliver_now(channel, address, "[Test] " + subject, templating.plain_text(text) if html else text, payload, (rule.ref_doctype, doc_name))})
    return {"subject": subject, "results": out}
