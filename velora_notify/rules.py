"""Validation of a Notification Rule: every mistake is caught when the rule is SAVED, not the first time a document triggers it."""
from __future__ import annotations

from urllib.parse import urlparse

from velora import throw
from velora.meta.registry import registry

from . import channels, expr, gateways, templating

RULE_FUNCS = set(expr.base_functions()) | {"changed", "transition", "has_role"}
BUILTIN_RECIPIENT = ("Field", "Role", "User", "Email", "Expression", "Phone Field", "Phone", "CC Field", "CC Email", "BCC Field", "BCC Email")


def _compile(src, what):
    try:
        expr.compile_expr(src, functions=RULE_FUNCS)
    except expr.ExprError as e:
        throw(f"{what}: {e}")


def validate_rule(r) -> None:
    dt = (r.ref_doctype or "").strip()
    if not registry.exists(dt):
        throw(f"{dt!r} is not a DocType")
    if dt.startswith("Notification "):
        throw("A rule cannot be about notifications themselves (that would loop)")
    meta = registry.get(dt)
    if meta.istable:
        throw("Child tables have no events of their own: attach the rule to the parent document")
    r.ref_doctype = dt
    fields = {f.fieldname: f for f in meta.fields if not f.is_layout}
    ev = r.event
    if ev == "Value Change":
        if r.value_field not in fields:
            throw(f"'Field' must be a field of {dt} for a Value Change rule")
    elif ev in ("Days Before", "Days After"):
        f = fields.get(r.value_field)
        if not f or f.fieldtype not in ("Date", "Datetime"):
            throw(f"'Field' must be a date field of {dt} for a {ev} rule")
        if r.days is None or not 0 <= int(r.days) <= 3650:
            throw("'Days' must be between 0 and 3650")
    elif ev == "Custom":
        if not (r.custom_event or "").strip():
            throw("Name the custom event (the name your code passes to velora_notify.trigger)")
    elif ev in ("Submit", "Cancel") and not meta.is_submittable:
        throw(f"{dt} cannot be submitted, so a {ev} rule can never fire")
    if (r.condition or "").strip():
        _compile(r.condition, "Condition")
    else:
        r.condition = None
    for label, src in (("Subject", r.subject), ("Message", r.message)):
        try:
            templating.validate(src, templating.MAX_BROADCAST if label == "Message" and getattr(r, "message_format", None) == "HTML" else templating.MAX_TEMPLATE)
        except templating.TemplateError as e:
            throw(f"{label}: {e}")
    chs = list(r.channels or [])
    if not chs:
        throw("Choose at least one channel")
    seen = set()
    for i, c in enumerate(chs, 1):
        if c.channel not in channels.names():
            throw(f"Channel row {i}: no sender is registered for {c.channel}. Register one with velora_notify.channels.register({c.channel!r}, send)")
        if c.channel == "Webhook":
            u = urlparse(c.webhook_url or "")
            if u.scheme not in ("https", "http") or not u.hostname:
                throw(f"Channel row {i}: a Webhook needs a valid URL")
        elif c.webhook_url:
            throw(f"Channel row {i}: only a Webhook channel has a URL")
        key = (c.channel, c.webhook_url or "")
        if key in seen:
            throw(f"Channel row {i}: {c.channel} is listed twice")
        seen.add(key)
    needs_people = any(c.channel != "Webhook" for c in chs)
    rcp = list(r.recipients or [])
    if needs_people and not rcp:
        throw("Say who should receive it (Send to)")
    if any(c.channel in gateways.PHONE_CHANNELS for c in chs) and not any(p.recipient_type in ("Phone Field", "Phone") for p in rcp):
        throw("SMS and WhatsApp need a phone number: add a recipient of type Phone Field (a field holding the number) or Phone")
    for i, p in enumerate(rcp, 1):
        v = (p.value or "").strip()
        if p.recipient_type in ("Field", "Phone Field", "CC Field", "BCC Field") and v not in fields:
            throw(f"Recipient row {i}: {v!r} is not a field of {dt}")
        if p.recipient_type == "Phone" and not gateways.normalize_phone(v):
            throw(f"Recipient row {i}: {v!r} is not a valid phone number")
        if p.recipient_type in ("CC Email", "BCC Email") and not channels.valid_email(v):
            throw(f"Recipient row {i}: {v!r} is not a valid email address")
        if p.recipient_type == "Expression":
            _compile(v, f"Recipient row {i}")
        if p.recipient_type == "Email" and not channels.valid_email(v):
            throw(f"Recipient row {i}: {v!r} is not a valid email address")
        if p.recipient_type in ("Role", "User") and not v:
            throw(f"Recipient row {i}: enter the {p.recipient_type.lower()}")
    if r.throttle_minutes is not None and int(r.throttle_minutes) < 0:
        throw("'Do not repeat within' cannot be negative")
    if r.escalate_after:
        if int(r.escalate_after) < 1:
            throw("'Escalate if unread after' must be at least 1 minute")
        if not r.escalate_to_type or not (r.escalate_to or "").strip():
            throw("Say who to escalate to")
        if "In-App" not in {c.channel for c in chs}:
            throw("Escalation works on unread in-app notifications: add the In-App channel")
