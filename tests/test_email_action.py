"""Emailing a document: it needs the 'email' permission, validates what it is given, and explains every failure (it used to answer every one with a bare HTTP 500)."""
import pytest
from fastapi.testclient import TestClient

import velora.api.document_actions as da
from velora import new_doc
from velora.api import create_app

from test_notify import ns  # noqa: F401  (demo + notifications apps)

H = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


@pytest.fixture
def api(ns, monkeypatch):
    real = da.check_permission
    monkeypatch.setattr(da, "check_permission", lambda meta, ptype, *a, **k: None if ptype == "email" else real(meta, ptype, *a, **k))
    customer = new_doc("Customer", customer_name="Acme").insert()
    sent = []
    import velora_notify.channels as ch
    monkeypatch.setattr(ch, "send_email", lambda d, cfg_all=None: sent.append(d))
    return TestClient(create_app(auto_init=False), raise_server_exceptions=False), customer.name, sent, monkeypatch


def post(api, **body):
    c, name, *_ = api
    return c.post(f"/api/email/Customer/{name}", json=body, headers=H)


def test_a_valid_request_sends_one_message(api):
    r = post(api, recipient="ada@acme.ng", subject="Statement", message="See attached")
    assert r.status_code == 200 and r.json()["data"] == {"sent": True, "recipient": "ada@acme.ng"}
    assert api[2] == [{"recipient": "ada@acme.ng", "subject": "Statement", "body": "See attached", "payload": {"doctype": "Customer", "name": api[1]}}]
    post(api, recipient="ada@acme.ng")
    assert api[2][1]["subject"] == f"Customer: {api[1]}" and api[2][1]["body"].startswith("Please find the Customer record")        # sensible defaults


@pytest.mark.parametrize("recipient,frag", [("", "Give the address"), ("not-an-email", "not a valid email"), ("a@b.co\r\nBcc: x@y.co", "not a valid email"), ("a@b.co\nBcc: x@y.co", "not a valid email"),
                                           ("a@b.co, c@d.co", "not a valid email"), ("x" * 300 + "@acme.ng", "not a valid email")])
def test_bad_addresses_are_refused_before_anything_is_sent(api, recipient, frag):
    r = post(api, recipient=recipient)
    assert r.status_code == 422 and frag in r.json()["message"] and api[2] == []


def test_oversized_subjects_and_messages_are_refused(api):
    assert post(api, recipient="a@b.co", subject="s" * 201).status_code == 422
    assert post(api, recipient="a@b.co", message="m" * 20001).status_code == 422
    assert post(api, recipient="a@b.co", subject="s" * 200, message="m" * 20000).status_code == 200 and len(api[2]) == 1


def test_every_way_the_mail_can_fail_is_explained_never_a_bare_500(api):
    import smtplib
    import velora_notify.channels as ch
    for exc, frag in ((ch.PermanentError("Email is not set up: configure notify.settings.email"), "not set up"), (ch.PermanentError("The server refused the recipient"), "refused the recipient"),
                      (ConnectionRefusedError("[Errno 111] Connection refused"), "could not be reached"), (TimeoutError("timed out"), "could not be reached"),
                      (smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "could not be reached"), (smtplib.SMTPResponseException(451, b"try later"), "could not be reached")):
        def boom(d, cfg_all=None, _e=exc):
            raise _e
        api[3].setattr(ch, "send_email", boom)
        r = post(api, recipient="a@b.co")
        assert r.status_code == 422 and frag in r.json()["message"], (exc, r.status_code, r.text)


def test_the_email_permission_is_still_required(ns):
    c = TestClient(create_app(auto_init=False), raise_server_exceptions=False)
    customer = new_doc("Customer", customer_name="Acme").insert()
    r = c.post(f"/api/email/Customer/{customer.name}", json={"recipient": "a@b.co"}, headers=H)
    assert r.status_code == 403 and "no 'email' permission" in r.json()["message"]
    assert c.post(f"/api/email/Customer/{customer.name}", json={"recipient": "a@b.co"}).status_code in (401, 403)           # and signing in is
    assert c.post("/api/email/Customer/NOPE", json={"recipient": "a@b.co"}, headers=H).status_code in (403, 404)
