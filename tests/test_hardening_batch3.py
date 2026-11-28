"""Print previews cannot run a template author's script, website links cannot leave the site by a trick, and nobody can send unlimited mail through the company account."""
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

import velora.api.document_actions as da
import velora.printing as printing
from velora import db, new_doc
from velora.api import create_app
from velora.db.system import export_log
from velora.exceptions import ValidationError
from velora.printing import render as render_print, save as save_print
from velora.settings import set_setting
from velora.website import save as save_page

from test_email_action import H, api, post  # noqa: F401  (the same fixtures the email action tests use)
from test_notify import ns  # noqa: F401

ALICE = {"X-Velora-User": "alice", "X-Velora-Roles": "System Manager"}
HOSTILE = "<script>alert('author script')</script><img src=x onerror=alert(1)><p onclick='steal()'>{{ customer_name }}</p>"


# ============================== print previews ==============================
@pytest.fixture
def preview(site, monkeypatch):
    real = printing.check_permission
    monkeypatch.setattr(printing, "check_permission", lambda meta, ptype, *a, **k: None if ptype == "print" else real(meta, ptype, *a, **k))
    customer = new_doc("Customer", customer_name="Acme <b>Ltd</b> & Sons").insert()
    fmt = save_print({"name": "Card", "doctype": "Customer", "template": HOSTILE})
    c = TestClient(create_app(auto_init=False), raise_server_exceptions=False)
    return c, f"/api/print/{fmt['id']}/Customer/{customer.name}", fmt["id"], customer.name


def test_a_print_preview_carries_a_policy_that_blocks_any_script_the_format_author_wrote(preview):
    c, url, *_ = preview
    r = c.get(url, headers=H)
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
    assert "default-src 'none'" in csp and "'unsafe-inline'" not in csp.split("style-src")[0] and "frame-ancestors 'none'" in csp and "form-action 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"
    scripts = re.findall(r"<script([^>]*)>", r.text)
    assert f"nonce='{nonce}'" in scripts[-1] and len(scripts) == 2                                         # Velora's own Print script (with the nonce) and the author's (without)
    assert not any("nonce" in s for s in scripts[:1])                                                      # the author's script has none: the browser will refuse to run it
    assert "onclick='window.print()'" not in r.text and "id='velora-print'" in r.text                        # our own button no longer needs an inline handler
    assert "Acme &lt;b&gt;Ltd&lt;/b&gt; &amp; Sons" in r.text                                              # and the document's values were never markup


def test_every_preview_gets_its_own_nonce(preview):
    c, url, *_ = preview
    nonces = {re.search(r"nonce-([^']+)'", c.get(url, headers=H).headers["content-security-policy"]).group(1) for _ in range(4)}
    assert len(nonces) == 4                                                                                  # a guessed or reused nonce would defeat the policy


def test_the_pdf_and_library_rendering_have_no_script_at_all(preview):
    c, url, rid, name = preview
    assert "nonce" not in render_print(rid, "Customer", name).replace("onerror", "").split("<script>alert")[0]          # no nonce'd script is added unless a nonce is given
    assert "velora-print').addEventListener" not in render_print(rid, "Customer", name)


# ============================== website links ==============================
def page(href=None, item=None, slug="home", **extra):
    block = {"type": "link", **({"href": href} if href else {}), **({"items": [{"label": "x", "href": item}]} if item else {})}
    return save_page({"slug": slug, "title": "Home", "body": "x", "blocks": [block], "published": True, **extra})


@pytest.mark.parametrize("bad", ["//evil.example", "//evil.example/path", "/\\evil.example", "/ok\nSet-Cookie: x=1", "/ok\x00", "/ok\r", "javascript:alert(1)", "data:text/html,x", "ftp://x"])
def test_links_that_leave_the_site_by_a_trick_are_refused(site, bad):
    with pytest.raises(ValidationError, match="must be relative, http, https or mailto"):
        page(href=bad)
    with pytest.raises(ValidationError, match="Navigation links must be relative"):
        page(item=bad)


@pytest.mark.parametrize("good", ["/about", "/a/b?x=1#top", "/", "https://example.com/x", "http://example.com", "mailto:hello@example.com"])
def test_ordinary_links_are_still_accepted(site, good):
    first = page(href=good)
    assert page(item=good, id=first["id"])["slug"] == "home"                                               # (saving again with the page's id updates it)


# ============================== email: a per-user hourly allowance ==============================
def test_a_user_cannot_send_more_than_the_hourly_limit_and_others_are_not_affected(api):
    set_setting("notify.settings", {"email": {"user_hourly_limit": 3}})
    c, name, sent, _ = api
    codes = [c.post(f"/api/email/Customer/{name}", json={"recipient": "a@acme.ng"}, headers=ALICE).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 422, 422] and len(sent) == 3
    r = c.post(f"/api/email/Customer/{name}", json={"recipient": "a@acme.ng"}, headers=ALICE)
    assert "already sent 3 emails in the last hour: the limit is 3" in r.json()["message"] and "user_hourly_limit" in r.json()["message"]
    bola = {"X-Velora-User": "bola", "X-Velora-Roles": "System Manager"}
    assert c.post(f"/api/email/Customer/{name}", json={"recipient": "a@acme.ng"}, headers=bola).status_code == 200      # someone else's allowance is their own


def test_a_failed_send_does_not_use_up_the_allowance(api):
    import velora_notify.channels as ch
    set_setting("notify.settings", {"email": {"user_hourly_limit": 2}})
    c, name, sent, mp = api
    mp.setattr(ch, "send_email", lambda d, cfg_all=None: (_ for _ in ()).throw(ch.PermanentError("Email is not set up")))
    for _ in range(6):
        assert c.post(f"/api/email/Customer/{name}", json={"recipient": "a@acme.ng"}, headers=ALICE).status_code == 422          # the mail server refuses each time ...
    mp.setattr(ch, "send_email", lambda d, cfg_all=None: sent.append(d))
    assert [c.post(f"/api/email/Customer/{name}", json={"recipient": "a@acme.ng"}, headers=ALICE).status_code for _ in range(2)] == [200, 200]   # ... and still two real sends are allowed


def test_only_the_last_hour_counts(api):
    set_setting("notify.settings", {"email": {"user_hourly_limit": 1}})
    c, name, sent, _ = api
    with db.transaction() as conn:
        conn.execute(insert(export_log).values(name="old-email", ref_doctype="Customer", owner="alice", creation=datetime.utcnow() - timedelta(hours=2), scope="email", row_count=1, detail={}))
    assert c.post(f"/api/email/Customer/{name}", json={"recipient": "a@acme.ng"}, headers=ALICE).status_code == 200            # two hours ago does not count
    assert c.post(f"/api/email/Customer/{name}", json={"recipient": "a@acme.ng"}, headers=ALICE).status_code == 422


def test_the_default_allowance_is_generous_and_the_setting_is_validated(api):
    assert da._email_limit() == 100
    for junk in ("many", None, 0, -5, {}):
        set_setting("notify.settings", {"email": {"user_hourly_limit": junk}})
        assert da._email_limit() >= 1
    set_setting("notify.settings", {"email": {"user_hourly_limit": "7"}})
    assert da._email_limit() == 7


def test_the_log_records_the_recipients_domain_not_the_address(api):
    c, name, *_ = api
    c.post(f"/api/email/Customer/{name}", json={"recipient": "private.person@client.example"}, headers=ALICE)
    with db.transaction() as conn:
        row = conn.execute(select(export_log).where(export_log.c.scope == "email")).mappings().first()
    assert row["detail"]["to_domain"] == "client.example" and "private.person" not in str(dict(row))


def test_saving_a_second_page_with_the_same_address_is_a_clear_error_not_a_database_crash(site):
    first = page(slug="about")
    with pytest.raises(ValidationError, match="A page with the address /about already exists"):
        page(slug="about")                                                                                   # used to be a raw IntegrityError (HTTP 500)
    other = page(slug="contact")
    with pytest.raises(ValidationError, match="already exists"):
        page(slug="about", id=other["id"])                                                                   # renaming one page onto another's address
    assert page(slug="about", id=first["id"])["id"] == first["id"]                                           # editing a page keeps its own address


def test_reserving_and_releasing_an_allowance_slot_outside_a_request(ns):
    """(Inside an API request the whole request rolls back on failure, which releases the slot by itself; these functions are the explicit form.)"""
    from velora.permissions import Session, session_as
    with session_as(Session("carol", frozenset({"System Manager"}))):
        slot = da._reserve_email_slot("Customer", "CUST-1", "x@client.example")
        with db.transaction() as c:
            assert c.execute(select(export_log.c.owner).where(export_log.c.name == slot)).scalar() == "carol"
        da._release_email_slot(slot)
        with db.transaction() as c:
            assert c.execute(select(export_log.c.name).where(export_log.c.name == slot)).first() is None
        da._release_email_slot(slot)                                                                         # releasing twice is harmless
        set_setting("notify.settings", {"email": {"user_hourly_limit": 1}})
        da._reserve_email_slot("Customer", "CUST-1", "x@client.example")
        with pytest.raises(ValidationError, match="the limit is 1"):
            da._reserve_email_slot("Customer", "CUST-1", "x@client.example")
