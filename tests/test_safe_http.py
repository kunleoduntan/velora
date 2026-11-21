"""Outbound webhooks cannot be aimed at the server's own network: not by an address, not by a name, and not by a name that changes its answer (DNS rebinding)."""
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from velora import integration_engine as ie
from velora import safe_http
from velora.safe_http import UnsafeTarget, blocked_reason
from velora.settings import set_setting
from velora_notify import channels

from test_notify import ns  # noqa: F401  (demo + notifications apps)

PUBLIC, PUBLIC6 = "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"


class Stop(OSError):
    """Raised by the test doubles at the moment a connection is attempted."""


def dns(monkeypatch, *answers):
    """A DNS server that gives these answers one after another (the last repeats): the first lookup is the CHECK, the next ones would be the CONNECT."""
    queue, calls = list(answers), []

    def fake(host, port, *a, **k):
        calls.append(host)
        addr = queue.pop(0) if len(queue) > 1 else queue[0]
        return [(socket.AF_INET6 if ":" in addr else socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port) if ":" not in addr else (addr, port, 0, 0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return calls


def record_connections(monkeypatch):
    seen = []

    def fake(address, *a, **k):
        seen.append(address)
        raise Stop("connection attempted")
    monkeypatch.setattr(safe_http.socket, "create_connection", fake)
    return seen


# ============================== which addresses are refused ==============================
@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1", "192.0.2.1", "198.18.0.1", "240.0.0.1",
    "::1", "::", "fe80::1", "fc00::1", "ff02::1",
    "::ffff:127.0.0.1", "::ffff:169.254.169.254", "::ffff:10.0.0.5",                         # IPv4 inside IPv6
    "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe",                                                 # NAT64: 127.0.0.1 and the cloud metadata address (is_global says True!)
    "2002:7f00:1::", "2002:a9fe:a9fe::",                                                     # 6to4
])
def test_internal_addresses_are_refused_in_every_disguise(address):
    assert blocked_reason(address) is not None


@pytest.mark.parametrize("address", [PUBLIC, PUBLIC6, "8.8.8.8", "1.1.1.1", "2001:4860:4860::8888", "64:ff9b::5db8:d822", "::ffff:93.184.216.34"])      # (the last two are IPv4 inside IPv6 for 93.184.216.34: a public target, so they are allowed)
def test_ordinary_public_addresses_are_allowed(address):
    assert blocked_reason(address) is None


def test_the_reason_names_what_was_hidden_inside(monkeypatch):
    assert "contains the private/internal address 127.0.0.1" in blocked_reason("64:ff9b::7f00:1")
    assert "is a private/internal address" in blocked_reason("10.1.2.3")


def test_one_bad_answer_among_good_ones_refuses_the_whole_name(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (PUBLIC, 443)), (2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(UnsafeTarget, match="private/internal"):
        safe_http.resolve("mixed.example.com", 443)                                          # an attacker cannot hide an internal address among public ones
    assert safe_http.resolve("mixed.example.com", 443, allow_private=True) == [PUBLIC, "127.0.0.1"]


def test_names_that_do_not_resolve_are_refused_with_a_plain_reason(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(UnsafeTarget, match="cannot resolve nowhere.example"):
        safe_http.resolve("nowhere.example", 443)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(UnsafeTarget, match="cannot resolve"):
        safe_http.resolve("empty.example", 443)


# ============================== the connection goes to the CHECKED address ==============================
def test_a_pinned_connection_reaches_the_pinned_address_whatever_the_name_would_resolve_to():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["host"], seen["body"] = self.headers["Host"], self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(204); self.end_headers()
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    conn = safe_http.PinnedHTTPConnection("webhook.invalid", srv.server_port, pinned_ip="127.0.0.1", timeout=5)      # ".invalid" can never resolve: reaching the server proves the pin was used
    conn.request("POST", "/hook", b"hello")
    assert conn.getresponse().status == 204
    conn.close(); srv.server_close()
    assert seen == {"host": f"webhook.invalid:{srv.server_port}", "body": b"hello"}                                  # the Host header is still the NAME


def test_tls_is_verified_against_the_original_hostname_not_the_address(monkeypatch):
    seen = record_connections(monkeypatch)
    conn = safe_http.PinnedHTTPSConnection("hooks.example.com", 443, pinned_ip=PUBLIC, timeout=5)
    with pytest.raises(Stop):
        conn.connect()
    assert seen == [(PUBLIC, 443)]
    wrapped = {}

    class Ctx:
        def wrap_socket(self, sock, server_hostname):
            wrapped["sni"] = server_hostname
            raise Stop()
    monkeypatch.setattr(safe_http.socket, "create_connection", lambda *a, **k: object())
    conn._context = Ctx()
    with pytest.raises(Stop):
        conn.connect()
    assert wrapped["sni"] == "hooks.example.com"                                                                      # certificate name checking uses the hostname


# ============================== DNS rebinding, end to end ==============================
def test_a_notification_webhook_is_not_fooled_by_a_name_that_changes_its_answer(ns, monkeypatch):
    set_setting("notify.settings", {})
    calls = dns(monkeypatch, PUBLIC, "127.0.0.1")                                  # the check sees a public address; any LATER lookup would see loopback
    seen = record_connections(monkeypatch)
    with pytest.raises(Stop):
        channels.send_webhook({"recipient": "https://rebind.example.com/hook", "name": "n"})
    assert seen == [(PUBLIC, 443)] and len(calls) == 1                             # connected to the checked address; the name was resolved ONCE


def test_a_notification_webhook_to_a_name_that_is_internal_is_refused_before_any_connection(ns, monkeypatch):
    set_setting("notify.settings", {})
    dns(monkeypatch, "64:ff9b::7f00:1")                                            # NAT64-wrapped 127.0.0.1
    seen = record_connections(monkeypatch)
    with pytest.raises(channels.PermanentError, match="Blocked: .*contains the private/internal address 127.0.0.1"):
        channels.send_webhook({"recipient": "https://sneaky.example.com/hook", "name": "n"})
    assert seen == []


def test_the_notification_webhook_can_still_be_allowed_to_reach_a_private_address_deliberately(ns, monkeypatch):
    set_setting("notify.settings", {"webhook": {"allow_private": True, "allow_http": True}})
    dns(monkeypatch, "10.0.0.5")
    seen = record_connections(monkeypatch)
    with pytest.raises(Stop):
        channels.send_webhook({"recipient": "http://intranet.example/hook", "name": "n"})
    assert seen == [("10.0.0.5", 80)]


def webhook(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("VELORA_INTEGRATION_MASTER_KEY", Fernet.generate_key().decode())
    return ie.create_webhook("ERP events", "https://rebind.example.com/hook", ["invoice.created"])


def test_an_integration_webhook_is_not_fooled_by_dns_rebinding_either(site, monkeypatch):
    dns(monkeypatch, PUBLIC)                                                       # registration: public
    webhook(monkeypatch)
    assert ie.enqueue_event("invoice.created", {"name": "INV-1"}) == 1
    dns(monkeypatch, PUBLIC, "127.0.0.1")                                          # delivery: public for the check, loopback for any later lookup
    seen = record_connections(monkeypatch)
    ie.deliver_webhooks()
    assert seen == [(PUBLIC, 443)]                                                 # never 127.0.0.1
    with ie.db.transaction() as c:
        job = c.execute(ie._queue.select()).mappings().one()
    assert job["status"] != "Sent" and "connection attempted" in str(job["last_error"])


def test_an_integration_webhook_whose_name_turned_internal_is_not_contacted(site, monkeypatch):
    dns(monkeypatch, PUBLIC)
    webhook(monkeypatch)
    ie.enqueue_event("invoice.created", {"name": "INV-2"})
    dns(monkeypatch, "169.254.169.254")                                            # the name now points at the cloud metadata service
    seen = record_connections(monkeypatch)
    ie.deliver_webhooks()
    assert seen == []
    with ie.db.transaction() as c:
        job = c.execute(ie._queue.select()).mappings().one()
    assert job["status"] != "Sent" and "public IP" in str(job["last_error"])


def test_registering_a_webhook_aimed_inside_is_refused(site, monkeypatch):
    for answer in ("127.0.0.1", "10.0.0.5", "64:ff9b::7f00:1", "::ffff:127.0.0.1"):
        dns(monkeypatch, answer)
        with pytest.raises(Exception, match="public IP"):
            ie.create_webhook("x", "https://evil.example.com/hook", ["invoice.created"])
    dns(monkeypatch, PUBLIC)
    for url in ("http://example.com/hook", "https://example.com:8443/hook", "https://user:pw@example.com/hook"):
        with pytest.raises(Exception, match="HTTPS URL on the standard port"):
            ie.create_webhook("x", url, ["invoice.created"])
