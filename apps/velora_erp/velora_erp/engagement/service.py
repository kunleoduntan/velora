"""Relationship moments: who deserves a kind word today, and the message that goes to them.

Sources (all optional, all switchable in Engagement Settings):
  * Party Important Date: birthdays and anniversaries entered for customers, suppliers and employees;
  * Employee records: birthdays and work anniversaries (date of birth, date of joining);
  * Customer and Supplier records: the anniversary of the day they joined;
  * Occasion: the festive calendar (New Year, Christmas, Eid, ...);
  * quiet customers (and, if wanted, suppliers) who have not been invoiced for a while;
  * any installed app, through the `engagement_moments_provider` hook (Farepoint adds bon voyage and welcome home).

A moment is logged once (the Engagement Log key makes a repeat run harmless), rendered into a branded email, checked against the opt-out list, and either
queued in the notification outbox or held for a person to release, depending on the switch in Engagement Settings.
"""
from __future__ import annotations

import importlib
import logging
import re
from datetime import date, datetime, timedelta

from velora import db, get_doc, get_list, new_doc

from . import branding

log = logging.getLogger(__name__)
SETTINGS = "Primary"
NAME_FIELD = {"Customer": "customer_name", "Supplier": "supplier_name", "Employee": "employee_name"}
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
DEFAULT_SUBJECT = {"Birthday": "Happy birthday, {{ first_name }}!", "Work Anniversary": "Congratulations, {{ first_name }}", "Partnership Anniversary": "Thank you, {{ first_name }}",
                   "Holiday": "{{ occasion }} greetings from {{ company }}", "Win Back": "We miss you, {{ first_name }}", "Custom": "A note from {{ company }}"}
FALLBACK_BODY = "Dear {{ first_name }},\n\nEveryone at {{ company }} is thinking of you today. Thank you for being part of our story."


# ---- settings and contacts ---------------------------------------------------------------------------------------------------------------------
def settings():
    if db.exists("Engagement Settings", SETTINGS):
        return get_doc("Engagement Settings", SETTINGS, ignore_permissions=True)
    return new_doc("Engagement Settings", settings_name=SETTINGS).insert(ignore_permissions=True)


def _is_on(st, field) -> bool:
    return bool(int(st.get(field) or 0))


def fill(text: str, ctx: dict) -> str:
    return PLACEHOLDER.sub(lambda m: str(ctx.get(m.group(1), "")), text or "")


def _years(n: int | None) -> str:
    return "" if not n else ("1 year" if n == 1 else f"{n} years")


def _days(n: int | None) -> str:
    if not n:
        return ""
    if n >= 700:
        return f"{n // 365} years"
    if n >= 60:
        return f"{round(n / 30)} months"
    return f"{n} days"


def contact(party_type: str, party: str) -> dict | None:
    """Name, greeting name, email and phone of a customer, supplier or employee, or None when the record is gone or disabled."""
    if party_type == "Employee":
        fields = ["employee_name", "first_name", "preferred_name", "email", "personal_email", "mobile", "phone", "employment_status", "disabled"]
    else:
        fields = [NAME_FIELD[party_type], "email", "phone", "disabled"] + (["customer_type"] if party_type == "Customer" else ["supplier_type"])
    rows = get_list(party_type, filters=[["name", "=", party]], fields=fields, limit=1, ignore_permissions=True)
    if not rows:
        return None
    r = rows[0]
    if int(r.get("disabled") or 0) or r.get("employment_status") == "Left":
        return None
    full = r.get(NAME_FIELD[party_type]) or party
    if party_type == "Employee":
        first = r.get("preferred_name") or r.get("first_name") or full.split()[0]
        return {"full_name": full, "first_name": first, "email": r.get("email") or r.get("personal_email") or "", "phone": r.get("mobile") or r.get("phone") or ""}
    individual = (r.get("customer_type") or r.get("supplier_type")) == "Individual"
    return {"full_name": full, "first_name": full.split()[0] if individual else full, "email": r.get("email") or "", "phone": r.get("phone") or ""}


def _live_parties(party_type: str) -> list[dict]:
    flds = [NAME_FIELD[party_type], "email", "phone", "disabled", "creation"]
    if party_type == "Employee":
        flds = ["employee_name", "disabled", "employment_status", "date_of_birth", "date_of_joining"]
    return [r for r in get_list(party_type, fields=["name"] + flds, limit=200000, ignore_permissions=True)
            if not int(r.get("disabled") or 0) and r.get("employment_status") != "Left"]


# ---- moment sources ------------------------------------------------------------------------------------------------------------------------------
def _d(v):
    if not v:
        return None
    return v.date() if isinstance(v, datetime) else v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _same_day(d: date | None, on: date) -> bool:
    if not d:
        return False
    if (d.month, d.day) == (on.month, on.day):
        return True
    return (d.month, d.day) == (2, 29) and (on.month, on.day) == (2, 28) and on.year % 4 != 0     # a leap-day birthday is marked on 28 February in other years


def _important_dates(on, st):
    allow = {"Customer": "birthdays_customers", "Supplier": "birthdays_suppliers", "Employee": "birthdays_employees"}
    out = []
    for r in get_list("Party Important Date", filters=[["enabled", "=", 1]], fields=["name", "party_type", "party", "date_type", "label", "occasion_date", "repeat_yearly", "contact_email", "contact_phone"],
                      limit=200000, ignore_permissions=True):
        d = _d(r["occasion_date"])
        if not (_same_day(d, on) if int(r["repeat_yearly"] or 0) else d == on):
            continue
        if r["date_type"] == "Birthday":
            if not _is_on(st, allow[r["party_type"]]):
                continue
            kind = "Birthday"
        elif r["date_type"] == "Anniversary":
            if not _is_on(st, "work_anniversaries" if r["party_type"] == "Employee" else "partnership_anniversaries"):
                continue
            kind = "Work Anniversary" if r["party_type"] == "Employee" else "Partnership Anniversary"
        else:
            kind = "Custom"
        years = on.year - d.year if int(r["repeat_yearly"] or 0) and d.year < on.year else None
        out.append({"kind": kind, "party_type": r["party_type"], "party": r["party"], "key": f"date|{r['name']}|{on.year}", "occasion": r["label"] or "", "years": years,
                    "email": r["contact_email"] or "", "phone": r["contact_phone"] or "", "source": "Important Date"})
    return out


def _employee_moments(on, st):
    out = []
    if not (_is_on(st, "birthdays_employees") or _is_on(st, "work_anniversaries")):
        return out
    for e in _live_parties("Employee"):
        if _is_on(st, "birthdays_employees") and _same_day(_d(e.get("date_of_birth")), on):
            out.append({"kind": "Birthday", "party_type": "Employee", "party": e["name"], "key": f"emp|birthday|{e['name']}|{on.year}", "source": "Employee record"})
        j = _d(e.get("date_of_joining"))
        if _is_on(st, "work_anniversaries") and j and j.year < on.year and _same_day(j, on):
            out.append({"kind": "Work Anniversary", "party_type": "Employee", "party": e["name"], "years": on.year - j.year, "key": f"emp|anniversary|{e['name']}|{on.year}", "source": "Employee record"})
    return out


def _partnership(on, st):
    out = []
    if not _is_on(st, "partnership_anniversaries"):
        return out
    for t in ("Customer", "Supplier"):
        for p in _live_parties(t):
            c = _d(p.get("creation"))
            if c and c.year < on.year and _same_day(c, on):
                out.append({"kind": "Partnership Anniversary", "party_type": t, "party": p["name"], "years": on.year - c.year, "key": f"since|{t}|{p['name']}|{on.year}", "source": "Customer/Supplier record"})
    return out


def _holidays(on, st):
    out = []
    if not _is_on(st, "holidays_enabled"):
        return out
    flags = (("Customer", "to_customers"), ("Supplier", "to_suppliers"), ("Employee", "to_employees"))
    for o in get_list("Occasion", filters=[["enabled", "=", 1]], fields=["name", "occasion_name", "occasion_date", "repeat_yearly", "template", "to_customers", "to_suppliers", "to_employees"],
                      limit=1000, ignore_permissions=True):
        d = _d(o["occasion_date"])
        if not (_same_day(d, on) if int(o["repeat_yearly"] or 0) else d == on):
            continue
        for t, flag in flags:
            if not int(o.get(flag) or 0):
                continue
            for p in _live_parties(t):
                out.append({"kind": "Holiday", "party_type": t, "party": p["name"], "occasion": o["occasion_name"], "template": o["template"], "key": f"occ|{o['name']}|{t}|{p['name']}|{on.year}",
                            "source": "Occasion"})
    return out


def last_invoice_dates(party_type: str) -> dict[str, date]:
    doctype = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"
    last: dict[str, date] = {}
    for r in get_list(doctype, filters=[["docstatus", "=", 1]], fields=["party", "invoice_date"], limit=500000, ignore_permissions=True):
        d = _d(r["invoice_date"])
        if d and (r["party"] not in last or d > last[r["party"]]):
            last[r["party"]] = d
    return last


def _winback(on, st):
    out = []
    if not _is_on(st, "winback_enabled"):
        return out
    repeat = int(st.get("winback_repeat_days") or 120)
    nudged: dict[tuple, date] = {}
    for r in get_list("Engagement Log", filters=[["kind", "=", "Win Back"]], fields=["party_type", "party", "moment_date"], limit=500000, ignore_permissions=True):
        d = _d(r["moment_date"])
        if d and ((r["party_type"], r["party"]) not in nudged or d > nudged[(r["party_type"], r["party"])]):
            nudged[(r["party_type"], r["party"])] = d
    plan = [("Customer", int(st.get("winback_customer_days") or 180))] + ([("Supplier", int(st.get("winback_supplier_days") or 365))] if _is_on(st, "winback_suppliers") else [])
    for t, threshold in plan:
        live = {p["name"] for p in _live_parties(t)}
        for party, last in last_invoice_dates(t).items():
            quiet = (on - last).days
            if party not in live or quiet < threshold:
                continue
            prior = nudged.get((t, party))
            if prior and (on - prior).days < repeat:
                continue
            out.append({"kind": "Win Back", "party_type": t, "party": party, "days": quiet, "key": f"winback|{t}|{party}|{on.isoformat()}", "source": "Quiet party"})
    return out


def _providers(on):
    from velora.meta.registry import registry
    out = []
    for app in registry.apps:
        try:
            hooks = importlib.import_module(f"{app}.hooks")
            target = getattr(hooks, "engagement_moments_provider", None)
            if target:
                out.extend(importlib.import_module(target).moments(on) or [])
        except ModuleNotFoundError:
            continue
        except Exception:  # noqa: BLE001 - one app's mistake must not silence everyone else's moments
            log.exception("engagement provider of %s failed", app)
    return out


def moments(on: date | None = None, st=None) -> list[dict]:
    """Everything worth a kind word on the day, without writing anything. A person gets at most one moment of each kind per day."""
    on, st = on or date.today(), st or settings()
    seen, out = set(), []
    for source in (_important_dates, _employee_moments, _partnership, _holidays, _providers, _winback):
        for m in (source(on, st) if source is not _providers else _providers(on)):
            tag = (m["party_type"], m["party"], m["kind"], m.get("occasion") if m["kind"] in ("Holiday", "Custom") else "")
            if tag in seen:
                continue
            seen.add(tag)
            out.append(m)
    return out


def upcoming_employee_celebrations(on: date, days: int = 30) -> list[dict]:
    """First names and dates only, for the employee portal. Respects the birthday and anniversary switches."""
    st = settings()
    out = []
    for p in _live_parties("Employee"):
        first = (contact("Employee", p["name"]) or {}).get("first_name") or ""
        for kind, field, flag in (("Birthday", "date_of_birth", "birthdays_employees"), ("Work Anniversary", "date_of_joining", "work_anniversaries")):
            d = _d(p.get(field))
            if not d or not _is_on(st, flag) or (kind == "Work Anniversary" and d.year >= on.year and d >= on):
                continue
            try:
                nxt = d.replace(year=on.year)
            except ValueError:                      # 29 February in a year without one
                nxt = date(on.year, 2, 28)
            if nxt < on:
                nxt = nxt.replace(year=on.year + 1) if not (nxt.month == 2 and nxt.day == 29) else date(on.year + 1, 2, 28)
            if (nxt - on).days <= days:
                out.append({"date": nxt.isoformat(), "kind": kind, "first_name": first, "years": nxt.year - d.year if kind == "Work Anniversary" else None})
    return sorted(out, key=lambda r: (r["date"], r["first_name"]))


# ---- rendering ------------------------------------------------------------------------------------------------------------------------------------
def find_template(m: dict):
    names = [m.get("template")] if m.get("template") else []
    rows = get_list("Moment Template", filters=[["enabled", "=", 1], ["moment_kind", "=", m["kind"]]], fields=["name", "audience"], limit=100, ignore_permissions=True)
    for aud in (m["party_type"], "All"):
        names += [r["name"] for r in rows if r["audience"] == aud]
    return get_doc("Moment Template", names[0], ignore_permissions=True) if names else None


def compose(m: dict, who: dict, st, unsubscribe_url: str = "") -> dict:
    """Subject, plain text and branded HTML for one moment."""
    brand = st.get("brand_name") or "Our team"
    ctx = {"first_name": who["first_name"], "full_name": who["full_name"], "company": brand, "occasion": m.get("occasion") or "", "years_text": _years(m.get("years")), "days_text": _days(m.get("days"))}
    tpl = find_template(m)
    subject = fill((tpl.subject if tpl else DEFAULT_SUBJECT.get(m["kind"], DEFAULT_SUBJECT["Custom"])), ctx).strip()[:200]
    heading = fill((tpl.heading if tpl and tpl.heading else m.get("occasion") or subject), ctx)
    body = m["message"] if m.get("message") else fill(tpl.body if tpl else FALLBACK_BODY, ctx)
    if m.get("subject"):
        subject = m["subject"]
    signature = st.get("signature") or ""
    button_label = (tpl.button_label if tpl else "") or ""
    button_url = (tpl.button_url if tpl and tpl.button_url else (st.get("website_url") or (f"mailto:{st.get('reply_to')}" if st.get("reply_to") else ""))) if button_label else ""
    html = branding.render_email(brand=brand, logo_url=st.get("logo_url") or "", accent=(tpl.accent_colour if tpl and tpl.accent_colour else st.get("brand_colour") or "#0f6cbd"),
                                 emblem=(tpl.emblem if tpl and tpl.emblem else branding.EMBLEMS.get(m["kind"], "")), heading=heading, body=body, button_label=button_label,
                                 button_url=button_url, signature=signature, unsubscribe_url=unsubscribe_url, preheader=subject)
    text = f"{body}\n\n{signature}".strip()
    return {"subject": subject, "text": text, "html": html}


def preview(template: str, party_type: str = "Customer", party: str | None = None) -> dict:
    """What a template looks like, using a real party's name or a sample."""
    st = settings()
    tpl = get_doc("Moment Template", template, ignore_permissions=True)
    who = (contact(party_type, party) if party else None) or {"full_name": "Ada Okafor", "first_name": "Ada", "email": "", "phone": ""}
    m = {"kind": tpl.moment_kind, "party_type": party_type, "party": party or "SAMPLE", "template": template, "occasion": "Christmas Day" if tpl.moment_kind == "Holiday" else "",
         "years": 5 if "Anniversary" in tpl.moment_kind else None, "days": 200 if tpl.moment_kind == "Win Back" else None}
    return compose(m, who, st)


# ---- delivery ------------------------------------------------------------------------------------------------------------------------------------
def _messaging():
    try:
        from velora.meta.registry import registry
        from velora_notify import engine
        from velora_notify.broadcast import service as bc
        if not (registry.exists("Notification Delivery") and registry.exists("Communication Opt-Out")):
            return None, None
        return engine, bc
    except Exception:  # noqa: BLE001 - messaging is optional; moments are then prepared and held
        return None, None


def _queue(engine, bc, log_name: str, channel: str, address: str, msg: dict, unsubscribe_url: str) -> bool:
    from velora.document.document import now
    payload = {}
    if channel == "Email":
        payload = {"html": msg["html"], "unsubscribe_url": unsubscribe_url or None}
        st = settings()
        payload.update({"from_name": st.get("sender_name") or None, "reply_to": st.get("reply_to") or None})
        payload = {k: v for k, v in payload.items() if v}
    with db.transaction():
        return bool(engine._insert("Notification Delivery", dict(rule="(engagement)", channel=channel, recipient=address, user=None, subject=msg["subject"], body=msg["text"], status="Queued", attempts=0,
                                                              next_attempt=now(), idempotency_key=engine._key("eng", log_name, channel, address), ref_doctype="Engagement Log", ref_name=log_name,
                                                                  payload=payload, priority="Low")))


def _dispatch(log_doc, st) -> str:
    """Queue the logged message on every channel that has a good address. Returns the log status."""
    engine, bc = _messaging()
    if engine is None:
        return "Not Sent"
    sent, blocked = [], []
    for channel, on_, raw in (("Email", _is_on(st, "by_email"), log_doc.email), ("WhatsApp", _is_on(st, "by_whatsapp"), log_doc.phone)):
        if not on_:
            continue
        addr = bc.clean_address(raw, channel)
        if not addr:
            continue
        if bc.opted_out(addr, channel):
            blocked.append(channel)
            continue
        url = bc.unsubscribe_url(addr, channel) if channel == "Email" else ""
        msg = {"subject": log_doc.subject, "text": log_doc.message, "html": compose_html_with_link(log_doc, url) if channel == "Email" else ""}
        if _queue(engine, bc, log_doc.name, channel, addr, msg, url):
            sent.append(channel)
    log_doc.channels = ", ".join(sent)
    if sent:
        log_doc.detail = "Queued in the outbox."
        return "Queued"
    if blocked:
        log_doc.detail = "The address is on the opt-out list."
        return "Opted Out"
    log_doc.detail = "No usable address for the channels that are switched on."
    return "No Address"


def compose_html_with_link(log_doc, unsubscribe_url: str) -> str:
    """The stored branded email, with the personal unsubscribe link added to its footer."""
    html = log_doc.html or ""
    if not unsubscribe_url or "Unsubscribe" in html:
        return html
    link = f' <a href="{branding.escape(unsubscribe_url, quote=True)}" style="color:#718096;text-decoration:underline">Unsubscribe</a>'
    return html.replace("</td></tr></table></td></tr></table></body>", link + "</td></tr></table></td></tr></table></body>", 1)


def deliver(m: dict, on: date, st=None) -> str | None:
    """Log one moment (once) and send or hold it. Returns the status, or None when it was already handled."""
    st = st or settings()
    if get_list("Engagement Log", filters=[["idempotency_key", "=", m["key"]]], fields=["name"], limit=1, ignore_permissions=True):
        return None
    who = contact(m["party_type"], m["party"])
    if not who:
        return None
    who = {**who, "email": m.get("email") or who["email"], "phone": m.get("phone") or who["phone"]}
    msg = compose(m, who, st)
    doc = new_doc("Engagement Log", moment_date=on, kind=m["kind"], party_type=m["party_type"], party=m["party"], party_name=who["full_name"], status="Held", source=m.get("source") or "",
                  idempotency_key=m["key"], email=who["email"], phone=who["phone"], subject=msg["subject"], message=msg["text"], html=msg["html"])
    if _is_on(st, "send_automatically"):
        doc.status = _dispatch(doc, st)
    else:
        doc.detail = "Waiting for someone to release it (automatic sending is off)."
    doc.insert(ignore_permissions=True)
    return doc.status


def release(name: str) -> str:
    """Send a held moment now (also lets a person re-send one that found no address after fixing the record)."""
    st = settings()
    doc = get_doc("Engagement Log", name, ignore_permissions=True)
    if doc.status in ("Queued", "Released"):
        return doc.status
    doc.status = "Released" if _dispatch(doc, st) == "Queued" else doc.status
    if doc.status == "Released":
        doc.detail = "Released by a person and queued in the outbox."
    doc.save(ignore_permissions=True)
    return doc.status


def release_all_held() -> int:
    n = 0
    for r in get_list("Engagement Log", filters=[["status", "=", "Held"]], fields=["name"], limit=100000, ignore_permissions=True):
        if release(r["name"]) == "Released":
            n += 1
    return n


def run(on: date | None = None) -> dict:
    """The daily pass. Safe to run twice."""
    on, st = on or date.today(), settings()
    out: dict[str, int] = {}
    for m in moments(on, st):
        status = deliver(m, on, st)
        if status:
            out[status] = out.get(status, 0) + 1
    return out
