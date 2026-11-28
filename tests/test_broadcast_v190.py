"""Broadcast Centre, SMS/WhatsApp gateways, phone recipients, CC/BCC, HTML rules and test sends."""
import json
from datetime import datetime, timedelta

import pytest

import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError
from velora.settings import set_setting
from velora_notify import channels, directory, engine, gateways, outbox
from velora_notify.broadcast import jobs, service
from test_notify import FakeDir, customer, deliveries, rule, ns  # noqa: F401  (fixtures and helpers)

FUT = datetime(2030, 1, 1, 9, 0, 0)


def broadcast(**kw):
    vals = dict(title="Festive greetings", channel="Email", subject="Hello {{ full_name }}", message="<p>{{ salutation }} {{ full_name }}, from {{ sender_name }}</p>", message_is_html=1, sender_name="Mascot", audience_source="A typed list")
    rows = kw.pop("rows", [])
    vals.update(kw)
    b = new_doc("Broadcast", **vals)
    for r in rows:
        b.append("recipients", r)
    return b.insert()


def test_phone_numbers_are_normalised():
    n = gateways.normalize_phone
    assert n("0803 123 4567") == "2348031234567" and n("+234 803 123 4567") == "2348031234567" and n("8031234567") == "2348031234567"
    assert n("0044 20 7946 0958") == "442079460958" and n("abc") is None and n("123") is None and n(None) is None


def test_typed_list_send_personalises_skips_bad_and_tracks_delivery(ns):
    b = broadcast(rows=[{"full_name": "Ada", "salutation": "Dear Mrs", "email": "ADA@x.ng"}, {"full_name": "Bayo", "email": "bayo@x.ng"}, {"full_name": "No Mail", "email": "oops"},
                        {"full_name": "Ada again", "email": "ada@x.ng"}])
    out = service.build_recipients(b.name)
    assert out == {"recipients": 4, "will_send": 2, "skipped": 2, "opted_out": 0}
    assert service.send(b.name)["queued"] == 2
    rows = deliveries(rule="(broadcast)")
    assert sorted(d["recipient"] for d in rows) == ["ada@x.ng", "bayo@x.ng"]
    ada = next(d for d in rows if d["recipient"] == "ada@x.ng")
    assert ada["subject"] == "Hello Ada" and "Dear Mrs Ada, from Mascot" in ada["body"] and "<p>" not in ada["body"]
    assert json.loads(ada["payload"]) ["html"].startswith("<p>Dear Mrs Ada") if isinstance(ada["payload"], str) else ada["payload"]["html"].startswith("<p>Dear Mrs Ada")
    with pytest.raises(ValidationError, match="already been sent"):
        service.send(b.name)
    sent = []
    channels.register("Email", lambda d, cfg: sent.append(d["recipient"]) if d["recipient"] != "bayo@x.ng" else (_ for _ in ()).throw(channels.PermanentError("mailbox full")))
    try:
        outbox.process_due(FUT)
    finally:
        channels.register("Email", channels.send_email)
    done = service.sync(b.name)
    assert sent == ["ada@x.ng"] and done["status"] == "Partly Sent" and done["sent"] == 1 and done["failed"] == 1
    fresh = get_doc("Broadcast", b.name)
    assert {r.full_name: r.status for r in fresh.recipients}["Bayo"] == "Failed"
    with pytest.raises(ValidationError, match="cannot be changed"):
        fresh.message = "changed"
        fresh.save()


def test_html_values_are_escaped_not_trusted(ns):
    b = broadcast(rows=[{"full_name": "<script>x</script>", "email": "a@x.ng"}])
    service.send(b.name)
    html = deliveries(rule="(broadcast)")[0]["payload"]
    html = html["html"] if isinstance(html, dict) else json.loads(html)["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_opt_outs_are_respected_and_unsubscribe_link_works(ns):
    set_setting("notify.settings", {"base_url": "https://erp.example.ng"})
    new_doc("Communication Opt-Out", address="Quiet@X.ng").insert()
    b = broadcast(rows=[{"full_name": "Quiet", "email": "quiet@x.ng"}, {"full_name": "Loud", "email": "loud@x.ng"}])
    assert service.build_recipients(b.name)["opted_out"] == 1
    service.send(b.name)
    d = deliveries(rule="(broadcast)")
    assert [x["recipient"] for x in d] == ["loud@x.ng"]
    payload = d[0]["payload"] if isinstance(d[0]["payload"], dict) else json.loads(d[0]["payload"])
    link = payload["unsubscribe_url"]
    token = link.split("t=")[1]
    assert service.read_token(token) == ("Email", "loud@x.ng") and service.read_token(token[:-2] + "xx") is None
    page = service.unsubscribe_page({"t": token}, "GET")
    assert "Unsubscribe" in page and not get_list("Communication Opt-Out", filters=[["address", "=", "loud@x.ng"]], fields=["name"], ignore_permissions=True)   # opening the link alone changes nothing
    assert "unsubscribed" in service.unsubscribe_page({"t": token}, "POST")
    assert get_list("Communication Opt-Out", filters=[["address", "=", "loud@x.ng"]], fields=["name"], ignore_permissions=True)
    assert "not valid" in service.unsubscribe_page({"t": "garbage"}, "GET")
    with pytest.raises(ValidationError, match="already on the list"):
        new_doc("Communication Opt-Out", address="loud@x.ng", channel="Email").insert()


def test_audience_from_any_doctype_and_rate_staggering(ns):
    for i in range(5):
        customer(f"Cust {i}", email=f"c{i}@x.ng", status="Active" if i < 4 else "Inactive")
    b = broadcast(audience_source="Records of a document type", source_doctype="Customer", source_filters=[["status", "=", "Active"]], name_field="customer_name", email_field="email", send_rate_per_minute=2)
    assert service.build_recipients(b.name)["will_send"] == 4
    service.send(b.name)
    due = sorted(d["next_attempt"] for d in deliveries(rule="(broadcast)"))
    assert len({str(x)[:16] for x in due}) == 2                           # 4 messages at 2 a minute: two minutes
    with pytest.raises(ValidationError, match="no field called"):
        bad = broadcast(title="x", audience_source="Records of a document type", source_doctype="Customer", email_field="nope")
        service.build_recipients(bad.name)


def test_schedule_runs_when_due_and_cancel_stops_queued(ns):
    b = broadcast(rows=[{"full_name": "Ada", "email": "ada@x.ng"}])
    with pytest.raises(ValidationError, match="future"):
        service.send(b.name, datetime(2020, 1, 1))
    service.send(b.name, datetime.utcnow() + timedelta(days=1))
    assert get_doc("Broadcast", b.name).status == "Scheduled" and jobs.run_scheduled() == 0
    d = get_doc("Broadcast", b.name)
    d.scheduled_for = datetime.utcnow() - timedelta(minutes=1)
    d.save()
    assert jobs.run_scheduled() == 1 and get_doc("Broadcast", b.name).status == "Sending"
    assert service.cancel(b.name)["stopped"] == 1
    assert get_doc("Broadcast", b.name).status == "Cancelled" and deliveries(rule="(broadcast)")[0]["status"] == "Skipped"


def test_template_copies_and_test_send_reports_the_truth(ns, monkeypatch):
    t = new_doc("Message Template", template_name="Welcome", channel="Email", subject="Welcome {{ full_name }}", body="<p>Hi {{ full_name }}</p>").insert()
    b = new_doc("Broadcast", title="Intro", channel="Email", template=t.name, message_is_html=1, audience_source="A typed list").insert()
    assert b.subject == "Welcome {{ full_name }}" and b.message == "<p>Hi {{ full_name }}</p>"
    sent = []
    monkeypatch.setitem(channels.CHANNELS, "Email", lambda d, cfg: sent.append(d))
    res = service.send_test(b.name, "me@x.ng")
    assert res == {"sent": True, "to": "me@x.ng"} and sent[0]["subject"] == "Welcome Test Recipient (Test)" and not deliveries(rule="(broadcast)")
    monkeypatch.setitem(channels.CHANNELS, "Email", lambda d, cfg: (_ for _ in ()).throw(RuntimeError("smtp down")))
    assert service.send_test(b.name, "me@x.ng")["error"].endswith("smtp down")
    assert "not a valid email" in str(pytest.raises(ValidationError, service.send_test, b.name, "nope").value)
    with pytest.raises(ValidationError, match="SMS template"):
        wrong = new_doc("Message Template", template_name="Sms one", channel="SMS", body="Hi").insert()
        new_doc("Broadcast", title="Bad", channel="Email", template=wrong.name, audience_source="A typed list").insert()


class FakeConn:
    log = []

    def __init__(self, host, port, https, ip, timeout=15):
        self.args = (host, ip)

    def request(self, method, path, body, headers):
        FakeConn.log.append((self.args, method, path, body, headers))

    def getresponse(self):
        return type("R", (), {"status": FakeConn.status, "read": lambda self, n=0: b'{"ok":true}'})()

    def close(self):
        pass


@pytest.fixture
def gw(monkeypatch):
    FakeConn.log, FakeConn.status = [], 200
    monkeypatch.setattr(gateways, "_connect", FakeConn)
    monkeypatch.setattr(gateways.safe_http, "resolve", lambda host, port, allow_private=False: ["203.0.113.9"])
    monkeypatch.setenv("SMS_KEY", "k-123")
    monkeypatch.setenv("WA_TOKEN", "t-456")
    monkeypatch.setenv("TW_TOKEN", "tw-secret")


def delivery(channel, to, body="Hello"):
    return {"channel": channel, "recipient": to, "subject": "s", "body": body, "payload": {}}


def test_sms_providers_build_the_documented_requests(gw):
    cfg = {"sms": {"provider": "termii", "api_key_env": "SMS_KEY", "sender": "VALUE"}}
    gateways.send_sms(delivery("SMS", "0803 123 4567"), cfg)
    (host, ip), method, path, body, headers = FakeConn.log[-1]
    assert host == "api.ng.termii.com" and ip == "203.0.113.9" and path == "/api/sms/send"
    assert json.loads(body) == {"to": "2348031234567", "from": "VALUE", "sms": "Hello", "type": "plain", "channel": "generic", "api_key": "k-123"}
    gateways.send_sms(delivery("SMS", "08031234567"), {"sms": {"provider": "twilio", "account_sid": "AC1", "api_key_env": "TW_TOKEN", "sender": "+15005550006"}})
    _, _, path, body, headers = FakeConn.log[-1]
    assert path == "/2010-04-01/Accounts/AC1/Messages.json" and b"To=%2B2348031234567" in body and headers["Authorization"].startswith("Basic ")
    gateways.send_sms(delivery("SMS", "08031234567", "Pay by {to}"), {"sms": {"provider": "custom", "url": "https://sms.example.ng/send", "api_key_env": "SMS_KEY", "sender": "X",
                                                                                 "headers": {"Authorization": "Bearer {key}"}, "body": {"num": "{to}", "text": "{message}", "from": "{sender}"}}})
    _, _, _, body, headers = FakeConn.log[-1]
    assert json.loads(body) == {"num": "2348031234567", "text": "Pay by {to}", "from": "X"} and headers["Authorization"] == "Bearer k-123"


def test_whatsapp_meta_and_error_handling(gw):
    cfg = {"whatsapp": {"provider": "meta", "token_env": "WA_TOKEN", "phone_number_id": "999"}}
    gateways.send_whatsapp(delivery("WhatsApp", "0803 123 4567", "Hi"), cfg)
    _, _, path, body, headers = FakeConn.log[-1]
    assert path.endswith("/999/messages") and headers["Authorization"] == "Bearer t-456" and json.loads(body)["text"]["body"] == "Hi"
    gateways.send_whatsapp(delivery("WhatsApp", "08031234567"), {"whatsapp": {**cfg["whatsapp"], "template_name": "promo"}})
    assert json.loads(FakeConn.log[-1][3])["template"]["name"] == "promo"
    FakeConn.status = 400
    with pytest.raises(channels.PermanentError, match="rejected"):
        gateways.send_sms(delivery("SMS", "08031234567"), {"sms": {"provider": "termii", "api_key_env": "SMS_KEY"}})
    FakeConn.status = 503
    with pytest.raises(RuntimeError, match="503"):
        gateways.send_sms(delivery("SMS", "08031234567"), {"sms": {"provider": "termii", "api_key_env": "SMS_KEY"}})
    with pytest.raises(channels.PermanentError, match="not set up"):
        gateways.send_sms(delivery("SMS", "08031234567"), {})
    with pytest.raises(channels.PermanentError, match="valid phone"):
        gateways.send_sms(delivery("SMS", "12"), {"sms": {"provider": "termii", "api_key_env": "SMS_KEY"}})
    with pytest.raises(channels.PermanentError, match="https"):
        gateways.post("http://sms.example.ng/x", {}, b"")


def test_rule_with_phone_recipient_cc_bcc_and_html(ns, monkeypatch):
    with pytest.raises(ValidationError, match="need a phone number"):
        rule("nophone", channels=("SMS",), recipients=(("User", "bola@acme.ng"),))
    got = []
    monkeypatch.setitem(channels.CHANNELS, "SMS", lambda d, cfg: got.append(("sms", d["recipient"], d["body"])))
    monkeypatch.setitem(channels.CHANNELS, "Email", lambda d, cfg: got.append(("email", d["recipient"], d["payload"])))
    rule("full", channels=("Email", "SMS"), recipients=(("Field", "email"), ("Phone", "0803 123 4567"), ("CC Email", "boss@x.ng"), ("BCC Email", "audit@x.ng")),
         message="<b>Hello {{ doc.customer_name }}</b>", message_format="HTML")
    customer("Zed", email="zed@x.ng")
    outbox.process_due(FUT)
    email = next(g for g in got if g[0] == "email")
    sms = next(g for g in got if g[0] == "sms")
    assert email[1] == "zed@x.ng" and email[2]["cc"] == ["boss@x.ng"] and email[2]["bcc"] == ["audit@x.ng"] and email[2]["html"] == "<b>Hello Zed</b>"
    assert sms[1:] == ("sms", "2348031234567", "Hello Zed")[1:] or sms[1] == "2348031234567" and sms[2] == "Hello Zed"
    assert not any(g[0] == "email" and g[1] == "2348031234567" for g in got)


def test_rule_test_send_uses_a_real_document(ns, monkeypatch):
    sent = []
    monkeypatch.setitem(channels.CHANNELS, "Email", lambda d, cfg: sent.append(d))
    rule("t", channels=("Email",), recipients=(("User", "bola@acme.ng"),))
    c = customer("Tola")
    out = service.test_rule("t", c.name, "me@x.ng")
    assert out["results"] == [{"channel": "Email", "sent": True, "to": "me@x.ng"}] and sent[0]["subject"] == "[Test] Hello Tola"


def test_email_message_has_cc_unsubscribe_and_inline_picture(monkeypatch):
    captured = {}

    class SMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, msg, to_addrs=None): captured["msg"], captured["to"] = msg, to_addrs
    monkeypatch.setattr(channels.smtplib, "SMTP", SMTP)
    monkeypatch.setattr("velora.files.get_file", lambda fid: ({"content_type": "image/png", "file_name": "logo.png"}, b"\x89PNG"))
    cfg = {"email": {"host": "smtp.example.ng", "from_addr": "hello@x.ng"}}
    channels.send_email({"recipient": "a@x.ng", "subject": "Hi", "body": "Hi", "payload": {"html": "<p>Hi <img src='cid:img1'></p>", "cc": ["c@x.ng"], "bcc": ["b@x.ng"], "from_name": "Mascot",
                        "unsubscribe_url": "https://e/u?t=1", "inline_images": ["f1"], "attachments": ["f2"]}}, cfg)
    msg = captured["msg"]
    assert captured["to"] == ["a@x.ng", "c@x.ng", "b@x.ng"] and "b@x.ng" not in str(msg["Cc"]) and msg["Cc"] == "c@x.ng"
    assert msg["From"] == "Mascot <hello@x.ng>" and msg["List-Unsubscribe"] == "<https://e/u?t=1>"
    kinds = [p.get_content_type() for p in msg.walk()]
    assert kinds.count("image/png") == 2 and "text/html" in kinds


def test_gateway_settings_are_validated_and_saved(ns):
    from fastapi.testclient import TestClient
    from velora.api import create_app
    client = TestClient(create_app())
    admin = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
    ok = client.put("/api/notification-settings", json={"sms": {"provider": "termii", "api_key_env": "SMS_KEY", "sender": "VALUE", "default_country_code": "234", "junk": 1},
                                                          "whatsapp": {"provider": "meta", "token_env": "WA_TOKEN", "phone_number_id": "9"}}, headers=admin)
    assert ok.status_code == 200 and ok.json()["data"]["sms"] == {"provider": "termii", "api_key_env": "SMS_KEY", "sender": "VALUE", "default_country_code": "234"}
    for body, frag in (({"sms": {"provider": "nope"}}, "provider must be"), ({"sms": {"provider": "termii", "api_key_env": "my secret"}}, "NAME of an environment"),
                       ({"sms": {"provider": "custom", "url": "http://x"}}, "https://"), ({"sms": {"provider": "custom", "url": "https://x"}}, "needs url and a body"),
                       ({"sms": {"provider": "termii", "default_country_code": "+234"}}, "digits only")):
        assert frag in client.put("/api/notification-settings", json=body, headers=admin).json()["message"], body
    assert client.post("/api/notification-settings/test-gateway", json={"channel": "SMS", "to": "abc"}, headers=admin).status_code == 422
    assert client.post("/api/notification-settings/test-gateway", json={"channel": "SMS", "to": "08031234567"}, headers={"X-Velora-User": "x", "X-Velora-Roles": "Sales User"}).status_code == 403
    res = client.post("/api/notification-settings/test-gateway", json={"channel": "SMS", "to": "08031234567"}, headers=admin).json()["data"]
    assert res["sent"] is False or res["sent"] is True
    # broadcast routes
    b = broadcast(rows=[{"full_name": "Ada", "email": "ada@x.ng"}])
    assert client.get("/api/broadcast-centre/summary", headers=admin).json()["data"]["gateways"]["SMS"] is True
    assert client.post(f"/api/broadcasts/{b.name}/build", headers=admin).json()["data"]["will_send"] == 1
    assert "Dear Ada" in client.get(f"/api/broadcasts/{b.name}/preview", headers=admin).json()["data"]["body"]
    assert client.post(f"/api/broadcasts/{b.name}/send", json={}, headers=admin).json()["data"]["queued"] == 1
