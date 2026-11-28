"""The notification engine: a document event -> matching rules -> recipients -> preferences -> inbox (immediately) and outbox (for a worker).

Everything is written in the SAME transaction as the document, inside a savepoint: a notification can never be lost when the document commits, never appears for
a document that rolled back, and a broken rule can never make a save fail.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from velora import db, get_doc, get_list, realtime
from velora import site as site_mod
from velora.db.tables import get_table
from velora.document.document import now
from velora.permissions import get_session
from velora.settings import get_setting, set_setting

from . import gateways, channels, directory, expr, templating

TTL = 5.0
_cache: dict[int, tuple[float, dict]] = {}


def invalidate() -> None:
    _cache.clear()


def _ignored(doctype: str) -> bool:
    return doctype.startswith("Notification ")


def _load_all() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for n in get_list("Notification Rule", filters=[["enabled", "=", 1]], fields=["name"], limit=2000, ignore_permissions=True):
        r = get_doc("Notification Rule", n["name"], ignore_permissions=True).as_dict()
        try:
            r["_cond"] = expr.compile_expr(r["condition"]) if r.get("condition") else None
        except expr.ExprError as e:
            record_error(r["name"], f"condition: {e}")
            continue
        out.setdefault(r["ref_doctype"], []).append(r)
    return out


def rules_for(doctype: str) -> list[dict]:
    key = id(site_mod.current())
    hit = _cache.get(key)
    if hit is None or time.monotonic() - hit[0] > TTL:
        hit = (time.monotonic(), _load_all())
        _cache[key] = hit
    return hit[1].get(doctype, [])


def record_error(rule: str, error) -> None:
    try:
        errs = list(get_setting("notify.errors", []) or [])
        errs.append({"rule": rule, "error": str(error)[:300], "at": now().isoformat(timespec="seconds")})
        set_setting("notify.errors", errs[-20:])
    except Exception:  # noqa: BLE001 - recording a problem must never be the problem
        pass


@dataclass
class Rcpt:
    user: str | None
    email: str | None
    phone: str | None = None


def _sys() -> dict:
    t = now()
    return {"owner": "Notifications", "creation": t, "modified": t, "modified_by": "Notifications", "docstatus": 0, "idx": 0}


def _ctx(doc, old: dict | None, event: str, actor: str, rule: dict) -> dict:
    data = doc.as_dict()
    fields = {**expr.base_functions(), "doc": expr.DocView(data), "old": expr.DocView(old), "event": event, "user": actor, "rule": rule["name"]}
    fields["changed"] = lambda f: old is not None and _norm(old.get(f)) != _norm(data.get(f))
    fields["transition"] = lambda f, a, b: old is not None and old.get(f) == a and data.get(f) == b
    fields["has_role"] = lambda r: r in get_session().roles
    return fields


def _norm(v):
    return None if v in (None, "") else (str(v) if not isinstance(v, (int, float)) else v)


def _link(doc) -> str:
    base = (channels.settings().get("base_url") or "").rstrip("/")
    return f"{base}/#/app/{doc.doctype}/{doc.name}"


def _split(value) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else str(value).replace(";", ",").split(",")
    return [str(i).strip().lower() for i in items if str(i).strip()]


def _recipients(rule: dict, ctx: dict, doc, actor: str) -> list[Rcpt]:
    d = directory.get()
    out: dict[str, Rcpt] = {}
    phones: dict[str, Rcpt] = {}

    def add(item: str):
        item = item.strip().lower()
        if not item or item in out:
            return
        if d.is_user(item):
            out[item] = Rcpt(item, d.user_email(item))                           # a real user of this company: inbox + email
        elif "@" in item:
            out[item] = Rcpt(None, item)                                         # an outside address: email only
        # anything else (a stray word from a field or expression) is not a person: ignored
    for p in rule.get("recipients") or []:
        t, v = p["recipient_type"], (p["value"] or "").strip()
        if t == "Field":
            for i in _split(doc.get(v)):
                add(i)
        elif t == "Role":
            for u in d.users_with_role(v):
                add(u)
        elif t in ("User", "Email"):
            add(v)
        elif t == "Expression":
            for i in _split(expr.evaluate(v, ctx)):
                add(i)
        elif t in ("Phone Field", "Phone"):
            for raw in (_split(doc.get(v)) if t == "Phone Field" else [v]):
                number = gateways.normalize_phone(raw)
                if number and number not in phones:
                    phones[number] = Rcpt(None, None, number)
    if rule.get("exclude_actor"):
        out = {k: r for k, r in out.items() if (r.user or r.email or "").lower() != (actor or "").lower()}
    return list(out.values()) + list(phones.values())


def _copies(rule: dict, doc, ctx: dict | None = None) -> tuple[list[str], list[str]]:
    """Addresses that get a copy (CC) or a blind copy (BCC) of every email this rule sends."""
    cc, bcc = [], []
    for p in rule.get("recipients") or []:
        t, v = p["recipient_type"], (p["value"] or "").strip()
        if t not in ("CC Email", "CC Field", "BCC Email", "BCC Field"):
            continue
        found = _split(doc.get(v)) if t.endswith("Field") else [v.lower()]
        (cc if t.startswith("CC") else bcc).extend(a for a in found if channels.valid_email(a))
    return list(dict.fromkeys(cc)), [a for a in dict.fromkeys(bcc) if a not in cc]


@dataclass
class Prefs:
    email_enabled: bool = True
    quiet_start: str | None = None
    quiet_end: str | None = None
    digest: str = "Immediately"
    muted: frozenset = frozenset()


def _prefs(user: str, cache: dict) -> Prefs:
    if user not in cache:
        r = get_list("Notification Preference", filters=[["user", "=", user]], fields=["email_enabled", "quiet_start", "quiet_end", "digest", "muted_rules"], limit=1, ignore_permissions=True)
        cache[user] = Prefs(bool(r[0]["email_enabled"]), r[0]["quiet_start"] or None, r[0]["quiet_end"] or None, r[0]["digest"] or "Immediately",
                            frozenset(x.strip() for x in (r[0]["muted_rules"] or "").splitlines() if x.strip())) if r else Prefs()
    return cache[user]


def _hhmm(s: str | None):
    try:
        h, m = (s or "").split(":")
        return int(h) * 60 + int(m) if 0 <= int(h) < 24 and 0 <= int(m) < 60 else None
    except ValueError:
        return None


def quiet_until(at: datetime, start: str | None, end: str | None) -> datetime | None:
    """If `at` falls inside the quiet window (it may cross midnight), the moment it ends; else None."""
    a, b = _hhmm(start), _hhmm(end)
    if a is None or b is None or a == b:
        return None
    cur = at.hour * 60 + at.minute
    inside = (a <= cur < b) if a < b else (cur >= a or cur < b)
    if not inside:
        return None
    day = at.date() + timedelta(days=1 if (a > b and cur >= a) else 0)
    return datetime(day.year, day.month, day.day, b // 60, b % 60)


def digest_release(at: datetime, kind: str) -> datetime:
    if kind == "Hourly digest":
        return at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    nxt = at.replace(hour=8, minute=0, second=0, microsecond=0)
    return nxt if nxt > at else nxt + timedelta(days=1)


def _key(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:40]


def _insert(table: str, vals: dict) -> bool:
    t = get_table(table)
    c = db.conn()
    try:
        with c.begin_nested():
            c.execute(insert(t).values(**_sys(), name=secrets.token_hex(8), **vals))
        return True
    except IntegrityError:
        return False                                                   # the same notification was already created: exactly-once


def _throttled(table: str, who_col: str, who: str, rule: dict, doc, at: datetime) -> bool:
    m = int(rule.get("throttle_minutes") or 0)
    if m <= 0:
        return False
    t = get_table(table)
    ref = t.c.ref_name == doc.name
    with db.transaction() as c:
        return bool(c.execute(select(func.count()).select_from(t).where(t.c.rule == rule["name"], ref, getattr(t.c, who_col) == who, t.c.creation >= at - timedelta(minutes=m))).scalar())


def _apply(rule: dict, doc, event: str, old: dict | None, key_extra: str) -> int:
    actor = get_session().user
    ctx = _ctx(doc, old, event, actor, rule)
    if event == "Value Change" and not ctx["changed"](rule.get("value_field")):
        return 0
    if rule.get("_cond") is not None and not expr.evaluate(rule["_cond"], ctx):
        return 0
    link = _link(doc)
    tctx = {**{k: v for k, v in ctx.items() if k in ("doc", "old", "event", "user", "rule")}, "link": link}
    subject = templating.render(rule["subject"], tctx).strip()[:200]
    if rule.get("message_format") == "HTML":
        html = templating.render(rule["message"], tctx, html=True, limit=templating.MAX_BROADCAST, cap=templating.MAX_BROADCAST)
        return _enqueue(rule, doc, event, subject, templating.plain_text(html), link, actor, key_extra, html_body=html)
    text = templating.render(rule["message"], tctx)
    return _enqueue(rule, doc, event, subject, text, link, actor, key_extra)


def _enqueue(rule: dict, doc, event: str, subject: str, text: str, link: str, actor: str, key_extra: str = "", rcpts: list[Rcpt] | None = None, escalation: bool = False, html_body: str | None = None) -> int:
    at = now()
    rcpts = rcpts if rcpts is not None else _recipients(rule, {**expr.base_functions(), "doc": expr.DocView(doc.as_dict()), "old": expr.DocView(None), "event": event, "user": actor,
                                                              "has_role": lambda r: r in get_session().roles, "changed": lambda f: False, "transition": lambda *a: False}, doc, actor)
    base = (rule["name"], doc.doctype, doc.name, event, str(doc.get("modified") or ""), key_extra, "esc" if escalation else "")
    pcache: dict = {}
    payload = {"link": link, "event": event, "actor": actor}
    cc, bcc = _copies(rule, doc)
    n = 0
    for ch in rule.get("channels") or []:
        c = ch["channel"]
        if c == "In-App":
            for r in rcpts:
                if not r.user or rule["name"] in _prefs(r.user, pcache).muted or _throttled("Notification Log", "user", r.user, rule, doc, at):
                    continue
                made = _insert("Notification Log", dict(user=r.user, subject=subject, message=text, ref_doctype=doc.doctype, ref_name=doc.name, priority=rule.get("priority") or "Normal",
                                                        rule=rule["name"], read=0, escalated=1 if escalation else 0, delivery_key=_key(*base, r.user, "in-app")))   # an escalation notice must never escalate again
                if made:
                    realtime.notify(r.user)                       # the bell updates the moment this commits (nothing is sent if it rolls back)
                n += made
            continue
        targets = [Rcpt(None, ch["webhook_url"])] if c == "Webhook" else rcpts
        for r in targets:
            if c in gateways.PHONE_CHANNELS:
                if not r.phone:
                    continue                                       # SMS and WhatsApp go only to people we have a number for
            elif r.phone and not (r.email or r.user):
                continue                                           # a number alone cannot receive an email
            addr = r.phone if c in gateways.PHONE_CHANNELS else (r.email if c == "Email" else (ch["webhook_url"] if c == "Webhook" else (r.email or r.user)))
            pr = _prefs(r.user, pcache) if r.user else Prefs()
            if rule["name"] in pr.muted:
                continue
            who = addr or r.user or ""
            if c != "Webhook" and _throttled("Notification Delivery", "recipient", who, rule, doc, at):
                continue
            status, due, why = "Queued", at, None
            prio = rule.get("priority") or "Normal"
            if not addr:
                status, why = "Skipped", "no address for this recipient"
            elif c == "Email" and not pr.email_enabled:
                status, why = "Skipped", "the recipient turned email off"
            elif c in ("Email",) and prio != "Urgent":
                q = quiet_until(at, pr.quiet_start, pr.quiet_end)
                if q:
                    due = q
                if pr.digest != "Immediately":
                    status, due = "Held", max(due, digest_release(at, pr.digest))
            extra = {}
            if c == "Email":
                extra = {k: v for k, v in (("cc", cc), ("bcc", bcc), ("html", html_body)) if v}
            n += _insert("Notification Delivery", dict(rule=rule["name"], channel=c, recipient=addr, user=r.user, subject=subject, body=text, status=status, attempts=0, next_attempt=due,
                                                      last_error=why, idempotency_key=_key(*base, c, who), ref_doctype=doc.doctype, ref_name=doc.name, payload={**payload, **extra}, priority=prio))
    return n


def fire(doc, event: str, *, old: dict | None = None, custom: str | None = None, key_extra: str = "") -> int:
    """Create the notifications every matching rule asks for. Never raises."""
    if _ignored(doc.doctype):
        return 0
    n = 0
    with db.transaction():                          # joins the document's transaction; or opens one when app code calls this directly
        for rule in rules_for(doc.doctype):
            if rule["event"] != event or (event == "Custom" and rule.get("custom_event") != custom):
                continue
            try:
                with db.conn().begin_nested():
                    n += _apply(rule, doc, event, old, key_extra)
            except Exception as e:  # noqa: BLE001 - a broken rule must never fail the save that triggered it
                record_error(rule["name"], f"{type(e).__name__}: {e}")
    return n


def trigger(event: str, doc, key: str | None = None) -> int:
    """For app code: fire the rules whose event is Custom and named `event`. Pass a `key` to make a repeat of the same occurrence a no-op."""
    return fire(doc, "Custom", custom=event, key_extra=key or "")


# ---- document event handlers (registered in hooks.py) ----------------------------------------------------------------------------
def on_after_insert(doc):
    if _ignored(doc.doctype):
        return
    doc.flags._notify_new = True                    # the on_update that follows an insert is the same save: don't fire Save/Value Change for it
    fire(doc, "New")


def on_update(doc):
    if _ignored(doc.doctype):
        return
    if getattr(doc.flags, "_notify_new", False):
        doc.flags._notify_new = False
        return
    if int(doc.docstatus or 0) != 0:                # submit/cancel run on_update too; they have their own events
        return
    old = getattr(doc, "_old", None)
    fire(doc, "Save", old=old)
    fire(doc, "Value Change", old=old)


def on_submit(doc):
    fire(doc, "Submit", old=getattr(doc, "_old", None))


def on_cancel(doc):
    fire(doc, "Cancel", old=getattr(doc, "_old", None))


# ---- scheduled: reminders relative to a date, and escalation ---------------------------------------------------------------------------
def scan_date_rules(today=None) -> int:
    """Daily: 'N days before/after <date field>' reminders. Once per document per target date."""
    from datetime import date as _d
    today = today or _d.today()
    n = 0
    with db.transaction():
        n = _scan(today)
    return n


def _scan(today) -> int:
    n = 0
    for rules in list(_load_all().values()):
        for rule in rules:
            if rule["event"] not in ("Days Before", "Days After"):
                continue
            days = int(rule.get("days") or 0)
            target = today + timedelta(days=days) if rule["event"] == "Days Before" else today - timedelta(days=days)
            for r in get_list(rule["ref_doctype"], filters=[[rule["value_field"], "=", target], ["docstatus", "<", 2]], fields=["name"], limit=5000, ignore_permissions=True):
                try:
                    with db.conn().begin_nested():
                        n += _apply(rule, get_doc(rule["ref_doctype"], r["name"], ignore_permissions=True), rule["event"], None, target.isoformat())
                except Exception as e:  # noqa: BLE001
                    record_error(rule["name"], f"{type(e).__name__}: {e}")
    return n


def escalate(at: datetime | None = None) -> int:
    """Unread in-app notifications of a rule with 'escalate after N minutes' are passed to the escalation target, once."""
    with db.transaction():
        return _escalate(at or now())


def _escalate(at: datetime) -> int:
    n = 0
    log = get_table("Notification Log")
    for rules in list(_load_all().values()):
        for rule in rules:
            mins = int(rule.get("escalate_after") or 0)
            if mins <= 0:
                continue
            with db.transaction() as c:
                stale = c.execute(select(log.c.name, log.c.ref_doctype, log.c.ref_name, log.c.subject, log.c.message).where(
                    log.c.rule == rule["name"], log.c.read == 0, log.c.escalated == 0, log.c.creation <= at - timedelta(minutes=mins))).mappings().all()
            d = directory.get()
            targets = d.users_with_role(rule["escalate_to"]) if rule["escalate_to_type"] == "Role" else [rule["escalate_to"]]
            for s in stale:
                try:
                    with db.conn().begin_nested():
                        doc = get_doc(s["ref_doctype"], s["ref_name"], ignore_permissions=True)
                        n += _enqueue(rule, doc, "Escalation", f"Escalated: {s['subject']}", s["message"] or "", _link(doc), "Notifications", key_extra=s["name"],
                                      rcpts=[Rcpt(t.lower(), d.user_email(t.lower())) for t in targets if t], escalation=True)
                        db.conn().execute(update(log).where(log.c.name == s["name"]).values(escalated=1))
                except Exception as e:  # noqa: BLE001
                    record_error(rule["name"], f"escalation: {type(e).__name__}: {e}")
    return n


def preview(rule_name: str, doctype: str, name: str) -> dict:
    """What WOULD this rule do for this document? Nothing is sent or stored."""
    rule = get_doc("Notification Rule", rule_name, ignore_permissions=True).as_dict()
    doc = get_doc(doctype, name, ignore_permissions=True)
    actor = get_session().user
    ctx = _ctx(doc, None, rule["event"], actor, rule)
    try:
        cond = bool(expr.evaluate(rule["condition"], ctx)) if rule.get("condition") else True
    except expr.ExprError as e:
        return {"matches": False, "error": f"Condition: {e}"}
    link = _link(doc)
    tctx = {k: ctx[k] for k in ("doc", "old", "event", "user", "rule")} | {"link": link}
    return {"matches": cond, "subject": templating.render(rule["subject"], tctx).strip(), "message": templating.render(rule["message"], tctx),
            "channels": [c["channel"] for c in rule["channels"]],
            "recipients": [{"user": r.user, "email": r.email} for r in _recipients(rule, ctx, doc, actor)], "link": link}
