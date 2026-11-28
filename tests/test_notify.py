"""Notifications: rules, events, recipients, preferences, the outbox with retries, channels, escalation, digests and the API."""
import hmac
import hashlib
import json
import os
import smtplib
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

import velora
from velora import db, get_doc, get_list, new_doc
from velora.api import create_app
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora.settings import get_setting, set_setting
from velora_notify import channels, directory, engine, outbox

T0 = datetime(2026, 3, 2, 10, 0, 0)               # a Monday, 10:00
FUT = datetime(2030, 1, 1, 9, 0, 0)               # 'later than anything created with the real clock' - for processing the outbox
ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
ALICE = {"X-Velora-User": "alice@acme.ng", "X-Velora-Roles": "Sales User"}
BOLA = {"X-Velora-User": "bola@acme.ng", "X-Velora-Roles": "Sales User"}


class FakeDir:
    roles = {"Sales Manager": ["mo@acme.ng", "bola@acme.ng"], "Auditor": ["aud@acme.ng"]}
    known = {"alice@acme.ng", "bola@acme.ng", "mo@acme.ng", "aud@acme.ng", "boss@acme.ng", "ann@acme.ng"}

    def is_user(self, user):
        return user in self.known

    def users_with_role(self, role):
        return list(self.roles.get(role, []))

    def user_email(self, user):
        return user if user in self.known else None


@pytest.fixture(params=["sqlite"] + (["postgres"] if os.environ.get("VELORA_TEST_PG_URL") else []))
def ns(request, tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'n.db'}" if request.param == "sqlite" else os.environ["VELORA_TEST_PG_URL"]
    velora.init(velora.configure(db_url=url, apps=["velora_demo", "velora_notify"], developer_mode=True))
    if request.param == "postgres":
        from sqlalchemy import MetaData
        with db.transaction() as conn:
            md = MetaData()
            md.reflect(conn)
            md.drop_all(conn)
    velora.migrate()
    engine.invalidate()
    monkeypatch.setattr(directory, "get", lambda: FakeDir())
    yield
    velora.shutdown()


def rule(name="R", doctype="Customer", event="New", channels=("In-App",), recipients=(("User", "alice@acme.ng"),), **kw):
    r = new_doc("Notification Rule", rule_name=name, ref_doctype=doctype, event=event, subject=kw.pop("subject", "Hello {{ doc.customer_name }}"),
                message=kw.pop("message", "Message about {{ doc.customer_name }}"), **kw)
    for c in channels:
        r.append("channels", {"channel": c} if isinstance(c, str) else {"channel": c[0], "webhook_url": c[1]})
    for t, v in recipients:
        r.append("recipients", {"recipient_type": t, "value": v})
    return r.insert()


def customer(name="Acme", **kw):
    return new_doc("Customer", customer_name=name, status=kw.pop("status", "Active"), **kw).insert()


def logs(**flt):
    return get_list("Notification Log", filters=[[k, "=", v] for k, v in flt.items()], fields=["name", "user", "subject", "message", "read", "rule", "priority"], order_by="creation asc", ignore_permissions=True)


def deliveries(**flt):
    return get_list("Notification Delivery", filters=[[k, "=", v] for k, v in flt.items()],
                    fields=["name", "channel", "recipient", "status", "attempts", "next_attempt", "last_error", "subject", "body", "rule", "payload"], order_by="creation asc", ignore_permissions=True)


def bad(fn, frag):
    with pytest.raises(ValidationError, match=frag):
        fn()


# ====================================== rule validation ======================================
@pytest.mark.parametrize("kw,frag", [
    (dict(doctype="Ghost"), "'Ghost' is not a DocType"), (dict(doctype="Notification Log"), "loop"), (dict(doctype="Customer Contact"), "Child tables"),
    (dict(event="Value Change"), "must be a field of Customer"), (dict(event="Value Change", value_field="nope"), "must be a field"),
    (dict(event="Days Before", value_field="status", days=3), "must be a date field"), (dict(event="Custom"), "Name the custom event"),
    (dict(event="Submit"), "cannot be submitted"), (dict(condition="doc.__class__"), "Condition: '__class__' is not allowed"), (dict(condition="import os"), "Condition: Not a valid expression"),
    (dict(subject="{{ doc.name "), "Subject: Template error"), (dict(message="{% if %}"), "Message: Template error"), (dict(channels=()), "at least one channel"),
    (dict(channels=("Telegram",)), "no sender is registered for Telegram"), (dict(channels=("Webhook",)), "needs a valid URL"), (dict(channels=(("Webhook", "ftp://x"),)), "needs a valid URL"),
    (dict(channels=("In-App", "In-App")), "listed twice"), (dict(recipients=()), "Say who should receive"), (dict(recipients=(("Field", "nope"),)), "not a field of Customer"),
    (dict(recipients=(("Email", "not-an-email"),)), "not a valid email"), (dict(recipients=(("Expression", "doc.__x"),)), "Recipient row 1"), (dict(recipients=(("Role", ""),)), "enter the role"),
    (dict(throttle_minutes=-1), "cannot be negative"), (dict(escalate_after=30), "Say who to escalate to"),
    (dict(escalate_after=30, escalate_to_type="Role", escalate_to="Sales Manager", channels=("Email",)), "add the In-App channel"),
])
def test_a_bad_rule_is_refused_when_it_is_saved(ns, kw, frag):
    bad(lambda: rule(**kw), frag)


def test_a_good_rule_saves_and_a_webhook_rule_needs_no_recipients(ns):
    assert rule("A", channels=("In-App", "Email")).name == "A"
    assert rule("B", channels=(("Webhook", "https://example.com/hook"),), recipients=()).name == "B"
    assert rule("C", event="Days Before", doctype="Sales Order", value_field="order_date", days=3, subject="x", message="y").name == "C"
    assert rule("D", doctype="Sales Order", event="Submit", subject="x", message="y").name == "D"


# ====================================== events ======================================
def test_new_fires_once_and_the_insert_is_not_also_a_save(ns):
    rule("new", event="New"); rule("save", event="Save", subject="saved {{ doc.customer_name }}")
    c = customer()
    assert [l["rule"] for l in logs()] == ["new"]
    c.status = "Inactive"
    c.save()
    assert [l["rule"] for l in logs()] == ["new", "save"]                                                           # the update is a Save; the insert was not


def test_value_change_fires_only_when_that_field_really_changed(ns):
    rule("vc", event="Value Change", value_field="status", subject="{{ old.status }} -> {{ doc.status }}")
    c = customer()
    c.credit_limit = 99
    c.save()
    assert logs() == []                                                                                              # another field changed
    c.status = "Inactive"
    c.save()
    assert [l["subject"] for l in logs()] == ["Active -> Inactive"]
    c.save()
    assert len(logs()) == 1                                                                                          # unchanged: nothing


def test_conditions_decide_whether_a_rule_applies(ns):
    rule("big", condition="doc.credit_limit > 1000 and doc.status == 'Active'")
    customer("Small", credit_limit=10)
    assert logs() == []
    customer("Big", credit_limit=5000)
    assert len(logs()) == 1
    rule("changes", event="Save", condition='transition("status", "Active", "Blocked")', subject="blocked")
    c = customer("Third")
    c.status = "Inactive"; c.save()
    c.status = "Blocked"; c.save()
    assert [l["subject"] for l in logs(rule="changes")] == []                                                        # Inactive -> Blocked is not Active -> Blocked
    d = customer("Fourth")
    d.status = "Blocked"; d.save()
    assert [l["subject"] for l in logs(rule="changes")] == ["blocked"]


def test_submit_and_cancel_fire_and_do_not_also_look_like_a_save(ns):
    customer()
    rule("sub", doctype="Sales Order", event="Submit", subject="submitted {{ doc.name }}", message="x"); rule("can", doctype="Sales Order", event="Cancel", subject="cancelled", message="x")
    rule("sv", doctype="Sales Order", event="Save", subject="saved", message="x")
    so = new_doc("Sales Order", customer="CUST-0001"); so.append("items", {"description": "a", "qty": 1, "rate": 5}); so.insert()
    assert logs() == []                                                                                              # an insert is a New, not a Submit/Save/Cancel
    so.submit()
    assert [l["rule"] for l in logs()] == ["sub"] and logs()[0]["subject"] == f"submitted {so.name}"                 # the submit's internal on_update is not a "Save"
    so.cancel()
    assert [l["rule"] for l in logs()] == ["sub", "can"]


def test_custom_events_are_triggered_by_code_and_repeats_are_harmless(ns):
    rule("pay", event="Custom", custom_event="Payment Failed", subject="payment failed for {{ doc.customer_name }}")
    c = customer()
    assert engine.trigger("Payment Failed", c, key="attempt-1") == 1
    assert engine.trigger("Payment Failed", c, key="attempt-1") == 0                                                # the same occurrence: exactly once
    assert engine.trigger("Payment Failed", c, key="attempt-2") == 1
    assert engine.trigger("Something Else", c) == 0 and len(logs()) == 2


def test_days_before_and_after_a_date_fire_once_per_document_per_day(ns):
    customer()
    for d, n in ((date(2026, 3, 10), "A"), (date(2026, 3, 13), "B"), (date(2026, 3, 6), "C")):
        so = new_doc("Sales Order", customer="CUST-0001", order_date=d); so.append("items", {"description": n, "qty": 1, "rate": 1}); so.insert()
    rule("before", doctype="Sales Order", event="Days Before", value_field="order_date", days=3, subject="due in 3 days: {{ doc.name }}", message="x")
    rule("after", doctype="Sales Order", event="Days After", value_field="order_date", days=3, subject="3 days overdue: {{ doc.name }}", message="x")
    assert engine.scan_date_rules(date(2026, 3, 7)) == 1 and [l["rule"] for l in logs()] == ["before"]               # the 10th is 3 days after the 7th
    assert engine.scan_date_rules(date(2026, 3, 7)) == 0                                                            # a second scan the same day: nothing new
    assert engine.scan_date_rules(date(2026, 3, 9)) == 1 and [l["rule"] for l in logs()] == ["before", "after"]     # the 6th is 3 days before the 9th
    assert engine.scan_date_rules(date(2026, 3, 10)) == 1                                                           # the 13th is 3 days after the 10th


def test_a_broken_rule_never_fails_the_save_and_is_recorded(ns, monkeypatch):
    rule("ok", subject="fine")
    rule("boom", condition="doc.credit_limit / doc.status > 1")
    c = customer("Acme")
    assert c.name and [l["rule"] for l in logs()] == ["ok"]                                                          # the document saved, the good rule still fired
    errs = get_setting("notify.errors")
    assert errs[-1]["rule"] == "boom" and "cannot be combined" in errs[-1]["error"]


def test_notifications_are_part_of_the_documents_transaction(ns):
    rule("r", channels=("In-App", "Email"))
    with pytest.raises(RuntimeError):
        with db.transaction():
            customer("Rolled back")
            assert len(logs()) == 1 and len(deliveries()) == 1                                                       # visible inside the transaction ...
            raise RuntimeError("something later fails")
    assert logs() == [] and deliveries() == []                                                                       # ... and gone with it: no notification for a document that never existed


def test_disabled_rules_do_nothing_and_rule_changes_take_effect_at_once(ns):
    r = rule("r")
    r.enabled = 0
    r.save()
    customer("One")
    assert logs() == []
    r.enabled = 1
    r.save()
    customer("Two")
    assert len(logs()) == 1
    get_doc("Notification Rule", "r").delete()
    customer("Three")
    assert len(logs()) == 1


# ====================================== recipients ======================================
def test_recipients_from_fields_roles_users_expressions_and_the_actor_rule(ns):
    rule("multi", recipients=(("Field", "customer_name"), ("Role", "Sales Manager"), ("User", "aud@acme.ng"), ("Email", "outside@example.com"), ("Expression", "[doc.status, 'ann@acme.ng']")),
             channels=("In-App", "Email"), exclude_actor=0)
    customer("alice@acme.ng")
    assert sorted(l["user"] for l in logs()) == ["alice@acme.ng", "ann@acme.ng", "aud@acme.ng", "bola@acme.ng", "mo@acme.ng"]     # outside@... has no inbox (not a user here)
    em = {d["recipient"] for d in deliveries()}
    assert em == {"alice@acme.ng", "ann@acme.ng", "aud@acme.ng", "bola@acme.ng", "mo@acme.ng", "outside@example.com"}      # the stray word "active" is not a person: nobody is emailed or notified as "active"


def test_a_field_may_hold_several_people_and_nobody_is_notified_twice(ns):
    rule("many", recipients=(("Field", "customer_name"), ("User", "alice@acme.ng"), ("Role", "Sales Manager")), exclude_actor=0)
    customer("alice@acme.ng, bola@acme.ng; ghost@nowhere.io")
    assert sorted(l["user"] for l in logs()) == ["alice@acme.ng", "bola@acme.ng", "mo@acme.ng"]                      # deduplicated; a stranger gets no inbox entry


def test_the_person_who_made_the_change_is_not_notified_unless_asked(ns):
    rule("actor", recipients=(("Role", "Sales Manager"),))
    with session_as(Session("bola@acme.ng", frozenset({"System Manager"}))):
        customer("Acme")
    assert [l["user"] for l in logs()] == ["mo@acme.ng"]
    rule("actor2", recipients=(("Role", "Sales Manager"),), exclude_actor=0)
    with session_as(Session("bola@acme.ng", frozenset({"System Manager"}))):
        customer("Acme 2")
    assert sorted(l["user"] for l in logs(rule="actor2")) == ["bola@acme.ng", "mo@acme.ng"]


def test_templates_render_nothing_for_missing_values_never_the_word_none(ns):
    rule("t", subject="{{ doc.customer_name }}|{{ doc.credit_limit|money }}|{{ doc.missing }}|{{ old.status }}", message="{{ doc.customer_group }}!")
    customer("Acme")
    assert logs()[0]["subject"] == "Acme||" + "|" and logs()[0]["message"] == "!"


# ====================================== exactly-once, throttling, preferences ======================================
def test_the_same_notification_is_never_created_twice(ns):
    rule("dup", channels=("In-App", "Email"))
    c = customer()
    assert (len(logs()), len(deliveries())) == (1, 1)
    assert engine.fire(c, "New") == 0                                                                                # replaying the event (e.g. a retried request) adds nothing
    assert (len(logs()), len(deliveries())) == (1, 1)


def test_throttling_suppresses_repeats_inside_the_window_per_recipient(ns, monkeypatch):
    rule("thr", event="Save", throttle_minutes=30, channels=("In-App", "Email"), recipients=(("User", "alice@acme.ng"), ("User", "bola@acme.ng")))
    c = customer()
    clock = {"t": T0}
    monkeypatch.setattr(engine, "now", lambda: clock["t"])
    for i in range(3):
        c.credit_limit = i + 1
        c.save()
    assert len(logs()) == 2 and len(deliveries()) == 2                                                               # once per recipient, not once per save
    clock["t"] = T0 + timedelta(minutes=31)
    c.credit_limit = 99
    c.save()
    assert len(logs()) == 4 and len(deliveries()) == 4                                                               # the window has passed


def test_preferences_mute_rules_and_turn_email_off_without_touching_the_inbox(ns):
    rule("a", channels=("In-App", "Email")); rule("b", channels=("In-App", "Email"), subject="other")
    new_doc("Notification Preference", user="alice@acme.ng", email_enabled=0, muted_rules="b").insert()
    customer()
    assert sorted(l["rule"] for l in logs()) == ["a"]                                                                # rule b is muted completely
    d = deliveries()
    assert [(x["rule"], x["status"], x["last_error"]) for x in d] == [("a", "Skipped", "the recipient turned email off")]    # kept visibly, never sent


def test_urgent_ignores_quiet_hours_and_digests_but_normal_waits(ns, monkeypatch):
    new_doc("Notification Preference", user="alice@acme.ng", quiet_start="22:00", quiet_end="07:00").insert()
    rule("norm", channels=("Email",), subject="n"); rule("urg", channels=("Email",), priority="Urgent", subject="u")
    monkeypatch.setattr(engine, "now", lambda: datetime(2026, 3, 2, 23, 30))                                          # 23:30, inside quiet hours that cross midnight
    customer()
    d = {x["rule"]: x for x in deliveries()}
    assert d["norm"]["next_attempt"] == datetime(2026, 3, 3, 7, 0) and d["urg"]["next_attempt"] == datetime(2026, 3, 2, 23, 30)
    assert engine.quiet_until(datetime(2026, 3, 2, 3, 0), "22:00", "07:00") == datetime(2026, 3, 2, 7, 0)            # after midnight: ends this morning
    assert engine.quiet_until(datetime(2026, 3, 2, 12, 0), "22:00", "07:00") is None and engine.quiet_until(datetime(2026, 3, 2, 12, 0), "09:00", "17:00") == datetime(2026, 3, 2, 17, 0)
    assert engine.quiet_until(datetime(2026, 3, 2, 12, 0), "bad", "07:00") is None and engine.quiet_until(datetime(2026, 3, 2, 12, 0), "10:00", "10:00") is None


def test_digest_holds_then_sends_one_combined_message(ns, monkeypatch):
    new_doc("Notification Preference", user="alice@acme.ng", digest="Hourly digest").insert()
    rule("d1", channels=("Email",), subject="first {{ doc.customer_name }}"); rule("d2", channels=("Email",), subject="second {{ doc.customer_name }}")
    monkeypatch.setattr(engine, "now", lambda: datetime(2026, 3, 2, 10, 20))
    customer("Acme")
    held = deliveries()
    assert [h["status"] for h in held] == ["Held", "Held"] and all(h["next_attempt"] == datetime(2026, 3, 2, 11, 0) for h in held)
    assert outbox.release_digests(datetime(2026, 3, 2, 10, 59)) == 0                                                  # not yet
    assert outbox.release_digests(datetime(2026, 3, 2, 11, 0)) == 1
    d = deliveries()
    merged = [x for x in d if x["rule"] == "(digest)"]
    assert len(merged) == 1 and merged[0]["status"] == "Queued" and merged[0]["subject"] == "2 notifications" and "first Acme" in merged[0]["body"] and "second Acme" in merged[0]["body"]
    assert [x["status"] for x in d if x["rule"] != "(digest)"] == ["Sent", "Sent"] and outbox.release_digests(datetime(2026, 3, 2, 12, 0)) == 0
    assert engine.digest_release(datetime(2026, 3, 2, 7, 0), "Daily digest") == datetime(2026, 3, 2, 8, 0) and engine.digest_release(datetime(2026, 3, 2, 9, 0), "Daily digest") == datetime(2026, 3, 3, 8, 0)


def test_a_single_held_item_is_released_as_it_is(ns, monkeypatch):
    new_doc("Notification Preference", user="alice@acme.ng", digest="Daily digest").insert()
    rule("one", channels=("Email",))
    monkeypatch.setattr(engine, "now", lambda: datetime(2026, 3, 2, 10, 0))
    customer()
    outbox.release_digests(datetime(2026, 3, 3, 8, 0))
    d = deliveries()
    assert len(d) == 1 and d[0]["status"] == "Queued" and d[0]["subject"].startswith("Hello")


def test_recipients_without_an_address_are_skipped_visibly(ns):
    rule("noaddr", channels=("Email",), recipients=(("Expression", "['someone@elsewhere.org']"),))
    customer()
    assert [d["recipient"] for d in deliveries()] == ["someone@elsewhere.org"]                                       # an outside address is emailed directly


# ====================================== escalation ======================================
def test_unread_notifications_escalate_once_and_reading_stops_it(ns, monkeypatch):
    rule("esc", channels=("In-App", "Email"), escalate_after=30, escalate_to_type="Role", escalate_to="Sales Manager", subject="needs attention")
    monkeypatch.setattr(engine, "now", lambda: T0)
    customer("One")
    customer("Two")
    first = logs()[0]
    c = TestClient(create_app(auto_init=False))
    assert c.post(f"/api/notifications/{first['name']}/read", headers=ALICE).status_code == 200                      # alice reads the first one
    assert engine.escalate(T0 + timedelta(minutes=29)) == 0                                                          # not yet
    n = engine.escalate(T0 + timedelta(minutes=31))
    esc = [l for l in logs() if l["subject"].startswith("Escalated")]
    assert n >= 2 and sorted(l["user"] for l in esc) == ["bola@acme.ng", "mo@acme.ng"]                                # only the UNREAD one, to the role
    assert any(d["subject"].startswith("Escalated") for d in deliveries())
    assert engine.escalate(T0 + timedelta(hours=5)) == 0                                                             # escalated once, never again


# ====================================== the outbox ======================================
_q = iter(range(1, 10_000))


def queue_email(to="alice@acme.ng", **kw):
    rule(f"q{next(_q)}", channels=("Email",), recipients=(("User", to),), **kw)
    customer()
    return deliveries()[-1]


def set_email_cfg():
    set_setting("notify.settings", {"email": {"host": "smtp.test", "port": 587, "from_addr": "noreply@acme.ng", "user": "u", "password_env": "TEST_SMTP_PW"}})


class FakeSMTP:
    sent, logins, tls, fail = [], [], [], None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        FakeSMTP.tls.append(self.host)

    def login(self, u, p):
        FakeSMTP.logins.append((u, p))

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.tls, FakeSMTP.fail = [], [], [], None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("TEST_SMTP_PW", "s3cret")
    set_email_cfg()
    return FakeSMTP


def test_a_queued_email_is_sent_securely_and_marked_sent(ns, smtp):
    d = queue_email(subject="Hello\r\nBcc: attacker@evil.com", message="line1\nline2")
    assert outbox.process_due(FUT + timedelta(days=1)) == {"sent": 1, "retry": 0, "dead": 0, "taken_by_another_worker": 0}
    m = smtp.sent[0]
    assert m["To"] == "alice@acme.ng" and m["From"] == "noreply@acme.ng" and "\n" not in m["Subject"] and m["Bcc"] is None                  # header injection is impossible
    assert m.get_body(("plain",)).get_content().strip() == "line1\nline2" and "<a href=" in m.get_body(("html",)).get_content()
    assert smtp.tls == ["smtp.test"] and smtp.logins == [("u", "s3cret")]                                           # STARTTLS, and the password came from the environment
    assert get_doc("Notification Delivery", d["name"]).status == "Sent"
    assert outbox.process_due(FUT + timedelta(days=2))["sent"] == 0                                                   # never sent twice


def test_failures_back_off_then_die_and_can_be_retried_by_an_administrator(ns, smtp):
    d = queue_email()
    smtp.fail = smtplib.SMTPServerDisconnected("connection lost")
    now_ = FUT + timedelta(days=1)
    waits = []
    for i in range(5):
        res = outbox.process_due(now_)
        row = get_doc("Notification Delivery", d["name"])
        if row.status == "Queued":
            waits.append(int((row.next_attempt - now_).total_seconds()))
            assert row.attempts == i + 1 and "SMTPServerDisconnected" in row.last_error and res["retry"] == 1
            assert outbox.process_due(now_ + timedelta(seconds=1))["sent"] == 0                                      # not due again until the backoff has passed
            now_ = row.next_attempt
    assert waits == [60, 300, 1800, 7200]                                                                            # 1 min, 5 min, 30 min, 2 h ...
    row = get_doc("Notification Delivery", d["name"])
    assert row.status == "Dead" and row.attempts == 5 and "gave up after 5 attempts" in row.last_error                 # ... then Dead: visible, not silently dropped
    smtp.fail = None
    outbox.retry(d["name"])
    assert outbox.process_due(now_ + timedelta(minutes=1))["sent"] == 1
    with pytest.raises(ValueError, match="Only a Dead or Skipped"):
        outbox.retry(d["name"])


def test_permanent_errors_are_not_retried(ns, smtp):
    smtp.fail = smtplib.SMTPRecipientsRefused({"alice@acme.ng": (550, b"no such user")})
    d = queue_email()
    assert outbox.process_due(FUT + timedelta(days=1))["dead"] == 1
    row = get_doc("Notification Delivery", d["name"])
    assert row.status == "Dead" and row.attempts == 1 and "refused the recipient" in row.last_error
    smtp.fail = smtplib.SMTPResponseException(421, b"try later")
    d2 = queue_email("bola@acme.ng")
    assert outbox.process_due(FUT + timedelta(days=1))["retry"] == 2                                                  # 4xx is temporary (the new customer also matches the first rule: two deliveries)
    assert {x["status"] for x in deliveries() if x["name"] == d2["name"]} == {"Queued"}


def test_email_that_is_not_configured_or_has_a_bad_address_dies_with_a_clear_reason(ns, smtp):
    set_setting("notify.settings", {})
    d = queue_email()
    outbox.process_due(FUT + timedelta(days=1))
    assert "Email is not set up" in get_doc("Notification Delivery", d["name"]).last_error
    set_email_cfg()
    with pytest.raises(channels.PermanentError, match="not a valid email"):
        channels.send_email({"recipient": "no spaces@x", "subject": "s", "body": "b", "payload": {}})
    for evil in ("a@b.co\nBcc: x@y.z", "a@b.co, c@d.ef", "<a@b.co>", "a@b"):
        assert not channels.valid_email(evil), evil


def test_urgent_goes_first_and_a_delivery_taken_by_another_worker_is_left_alone(ns, smtp, monkeypatch):
    rule("lo", channels=("Email",), priority="Low", subject="low"); rule("hi", channels=("Email",), priority="Urgent", subject="urgent")
    customer()
    outbox.process_due(FUT + timedelta(days=1))
    assert [m["Subject"] for m in smtp.sent] == ["urgent", "low"]
    customer("Again")
    monkeypatch.setattr(outbox, "_claim", lambda name, at: False)                                                     # someone else got there first
    assert outbox.process_due(FUT + timedelta(days=1)) == {"sent": 0, "retry": 0, "dead": 0, "taken_by_another_worker": 2}
    assert len(smtp.sent) == 2


def test_a_worker_that_dies_mid_send_does_not_lose_the_message(ns, smtp):
    d = queue_email()
    t = outbox._t()
    with db.transaction() as c:
        c.execute(t.update().where(t.c.name == d["name"]).values(status="Sending", claimed_at=T0))
    assert outbox.recover_stuck(T0 + timedelta(minutes=5)) == 0                                                        # still plausibly sending
    assert outbox.recover_stuck(T0 + timedelta(minutes=11)) == 1
    row = get_doc("Notification Delivery", d["name"])
    assert row.status == "Queued" and row.attempts == 1 and "worker stopped" in row.last_error
    assert outbox.process_due(FUT + timedelta(days=1))["sent"] == 1


def test_claiming_is_atomic_across_workers(ns):
    from velora.db import get_engine
    if get_engine().dialect.name != "postgresql":
        pytest.skip("SQLite serialises writers; the race is verified on PostgreSQL")
    d = queue_email()
    wins = []
    ts = [threading.Thread(target=lambda: wins.append(outbox._claim(d["name"], T0))) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert wins.count(True) == 1


def test_a_channel_nobody_registered_is_dead_not_stuck_and_custom_channels_can_be_added(ns, monkeypatch):
    sent = []
    channels.register("Telegram", lambda d, cfg: sent.append((d["recipient"], d["body"])))
    try:
        rule("tg", channels=("Telegram",), recipients=(("User", "bola@acme.ng"),), message="hello by telegram")
        customer()
        assert outbox.process_due(FUT + timedelta(days=1))["sent"] == 1 and sent == [("bola@acme.ng", "hello by telegram")]
        monkeypatch.delitem(channels.CHANNELS, "Telegram")
        customer("Two")
        assert outbox.process_due(FUT + timedelta(days=1))["dead"] == 1
        assert "No sender is registered for Telegram" in [d for d in deliveries() if d["status"] == "Dead"][0]["last_error"]
    finally:
        channels.CHANNELS.pop("Telegram", None)


# ====================================== webhooks ======================================
class Hook(BaseHTTPRequestHandler):
    received, answer = [], 200

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Hook.received.append((self.path, dict(self.headers), body))
        self.send_response(Hook.answer)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def hook(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Hook.received, Hook.answer = [], 200
    monkeypatch.setenv("TEST_HOOK_SECRET", "topsecret")
    set_setting("notify.settings", {"webhook": {"allow_http": True, "allow_private": True, "secret_env": "TEST_HOOK_SECRET"}})
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_a_webhook_is_posted_as_signed_json_exactly_once_per_rule(ns, hook):
    rule("wh", channels=(("Webhook", hook + "/in?x=1"),), recipients=(), subject="S {{ doc.customer_name }}", message="M")
    customer("Acme")
    customer("Second")
    assert len(deliveries()) == 2                                                                                    # one per document, not per recipient
    assert outbox.process_due(FUT + timedelta(days=1))["sent"] == 2
    path, headers, body = Hook.received[0]
    assert path == "/in?x=1" and headers["Content-Type"] == "application/json" and headers["X-Velora-Delivery"]
    assert headers["X-Velora-Signature"] == "sha256=" + hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()   # the receiver can verify it came from us
    payload = json.loads(body)
    assert payload["subject"] == "S Acme" and payload["message"] == "M" and payload["doctype"] == "Customer" and payload["event"] == "New"


def test_webhook_failures_retry_or_die_by_the_receivers_answer(ns, hook):
    rule("wh", channels=(("Webhook", hook + "/x"),), recipients=())
    customer()
    Hook.answer = 503
    assert outbox.process_due(FUT + timedelta(days=1))["retry"] == 1
    Hook.answer = 400
    assert outbox.process_due(FUT + timedelta(days=2))["dead"] == 1
    assert "rejected it (400)" in deliveries()[0]["last_error"]


def test_webhooks_cannot_be_aimed_at_internal_services_by_default(ns, monkeypatch):
    set_setting("notify.settings", {})
    for url, frag in (("https://127.0.0.1/x", "private/internal"), ("https://169.254.169.254/latest", "private/internal"), ("https://10.0.0.5/x", "private/internal"),
                      ("http://example.com/x", "must use https"), ("ftp://example.com/x", "not a valid webhook URL"), ("https:///nohost", "not a valid webhook URL")):
        with pytest.raises(channels.PermanentError, match=frag):
            channels.send_webhook({"recipient": url, "name": "n"})
    monkeypatch.setattr(channels.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    class C:
        def __init__(self, *a, **k): pass
        def request(self, *a, **k): self.r = True
        def getresponse(self): return type("R", (), {"status": 204})()
        def close(self): pass
    channels.send_webhook({"recipient": "https://example.com/ok", "name": "n"}, opener=C)                            # a public address is fine


# ====================================== the API ======================================
@pytest.fixture
def client(ns):
    return TestClient(create_app(auto_init=False))


def test_my_inbox_shows_only_my_notifications_and_i_can_mark_them_read(ns, client):
    rule("mine", recipients=(("User", "alice@acme.ng"), ("User", "bola@acme.ng")), exclude_actor=0)
    customer("One"); customer("Two")
    r = client.get("/api/notifications", headers=ALICE).json()["data"]
    assert (r["unread"], r["total"], len(r["items"])) == (2, 2, 2) and all("alice" not in str(x.get("user", "")) for x in r["items"])
    mine = r["items"][0]["name"]
    assert client.post(f"/api/notifications/{mine}/read", headers=BOLA).status_code == 404                           # someone else's notification looks like a missing one
    assert client.post(f"/api/notifications/{mine}/read", headers=ALICE).status_code == 200
    assert client.get("/api/notifications?unread=1", headers=ALICE).json()["data"]["unread"] == 1
    assert client.get("/api/notifications?unread=1", headers=BOLA).json()["data"]["unread"] == 2                     # bola's own are untouched
    assert client.post("/api/notifications/read-all", headers=ALICE).json()["data"] == {"marked": 1}
    assert client.get("/api/notifications?limit=1&offset=1", headers=ALICE).json()["data"]["items"].__len__() == 1
    assert client.get("/api/notifications").status_code == 401


def test_the_generic_resource_api_does_not_leak_other_peoples_notifications(ns, client):
    rule("mine", recipients=(("User", "bola@acme.ng"),))
    customer()
    assert client.get("/api/resource/Notification Log", headers=ALICE).status_code == 403                             # only administrators may browse the raw log
    assert client.get("/api/resource/Notification Delivery", headers=ALICE).status_code == 403


def test_preferences_round_trip_and_are_validated(ns, client):
    p = client.get("/api/notification-preferences", headers=ALICE).json()["data"]
    assert p == {"email_enabled": True, "quiet_start": None, "quiet_end": None, "digest": "Immediately", "muted_rules": []}
    ok = {"email_enabled": False, "quiet_start": "22:00", "quiet_end": "07:00", "digest": "Daily digest", "muted_rules": ["a", " b ", ""]}
    assert client.put("/api/notification-preferences", json=ok, headers=ALICE).status_code == 200
    assert client.put("/api/notification-preferences", json={**ok, "digest": "Hourly digest"}, headers=ALICE).status_code == 200                # update, not duplicate
    got = client.get("/api/notification-preferences", headers=ALICE).json()["data"]
    assert got["email_enabled"] is False and got["digest"] == "Hourly digest" and got["muted_rules"] == ["a", "b"]
    assert client.get("/api/notification-preferences", headers=BOLA).json()["data"]["email_enabled"] is True                                 # everyone has their own
    for bad_body, frag in (({"quiet_start": "25:00", "quiet_end": "07:00"}, "HH:MM"), ({"quiet_start": "22:00"}, "both"), ({"digest": "Weekly"}, "Digest must be"), ({"muted_rules": "x"}, "list")):
        r = client.put("/api/notification-preferences", json=bad_body, headers=ALICE)
        assert r.status_code == 422 and frag in r.json()["message"], bad_body


def test_administrator_endpoints_deliveries_retry_settings_and_preview(ns, client, smtp):
    rule("adm", channels=("Email",), subject="Hi {{ doc.customer_name }}")
    c = customer("Acme")
    assert client.get("/api/notification-deliveries", headers=ALICE).status_code == 403
    r = client.get("/api/notification-deliveries?status=Queued", headers=ADMIN).json()["data"]
    assert len(r["items"]) == 1 and r["counts"] == {"Queued": 1}
    pv = client.post("/api/notification-rules/preview", json={"rule": "adm", "doctype": "Customer", "name": c.name}, headers=ADMIN).json()["data"]
    assert pv["matches"] is True and pv["subject"] == "Hi Acme" and pv["recipients"] == [{"user": "alice@acme.ng", "email": "alice@acme.ng"}] and pv["channels"] == ["Email"]
    assert len(deliveries()) == 1                                                                                    # a preview sends and stores nothing
    assert client.post("/api/notification-rules/preview", json={"rule": "adm"}, headers=ADMIN).status_code == 422
    assert client.post("/api/notification-rules/preview", json={"rule": "adm", "doctype": "Customer", "name": c.name}, headers=ALICE).status_code == 403
    d = r["items"][0]["name"]
    assert client.post(f"/api/notification-deliveries/{d}/retry", headers=ADMIN).status_code == 422                 # only Dead/Skipped can be retried
    t = client.put("/api/notification-settings", json={"email": {"host": "smtp.x", "from_addr": "a@b.co", "password_env": "SMTP_PASSWORD", "ignored": 1}, "base_url": "https://erp.acme.ng/"}, headers=ADMIN)
    assert t.status_code == 200 and t.json()["data"] == {"email": {"host": "smtp.x", "from_addr": "a@b.co", "password_env": "SMTP_PASSWORD"}, "base_url": "https://erp.acme.ng"}
    for body, frag in (({"email": {"host": "h", "from_addr": "a@b.co", "password_env": "hunter2!"}}, "NAME of an environment variable"), ({"email": {"host": ""}}, "host and a from_addr"),
                       ({"webhook": {"secret_env": "my secret"}}, "NAME of an environment variable"), ({"base_url": "ftp://x"}, "https://")):
        assert frag in client.put("/api/notification-settings", json=body, headers=ADMIN).json()["message"], body
    assert client.put("/api/notification-settings", json={}, headers=ALICE).status_code == 403
    set_email_cfg()
    assert client.post("/api/notification-settings/test-email", json={"to": "boss@acme.ng"}, headers=ADMIN).json()["data"] == {"sent": "boss@acme.ng"} and smtp.sent[-1]["Subject"] == "Velora test email"
    assert client.post("/api/notification-settings/test-email", json={"to": "bad"}, headers=ADMIN).status_code == 422
    assert client.get("/api/notification-channels", headers=ALICE).json()["data"]["channels"][:3] == ["In-App", "Email", "Webhook"]


def test_without_the_app_installed_the_endpoints_say_so(tmp_path):
    velora.init(velora.configure(db_url=f"sqlite:///{tmp_path / 'plain.db'}", apps=["velora_demo"], developer_mode=True))
    velora.migrate()
    try:
        r = TestClient(create_app(auto_init=False)).get("/api/notifications", headers=ALICE)
        assert r.status_code == 404 and "velora install-app velora_notify" in r.json()["message"]
    finally:
        velora.shutdown()
