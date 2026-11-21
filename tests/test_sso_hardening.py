"""SSO: a login can only be completed in the browser that started it, a transaction is single use even under a race, redirects cannot leave the site, and weak keys are refused."""
import base64
import json
import sqlite3
import threading
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from velora.controlplane.oidc_adapter import OIDCIDTokenVerifier
from velora.controlplane.sso_runtime import BIND_COOKIE, OIDCTransactionStore, SSOProvider, _safe_return_path, create_sso_router
from velora.exceptions import AuthenticationRequired

ISSUER, CLIENT = "https://id.example", "client-1"


# ============================== redirects ==============================
@pytest.mark.parametrize("bad", ["/\t/evil.example", "/\n/evil.example", "/\r/evil.example", "/\x0b/evil.example", "/\x00", "/\x7f", "/ok\x01", "//evil.example", "/\\evil.example",
                                 "https://evil.example", "evil", "", None, "javascript:alert(1)", "/a\tb"])
def test_a_return_path_that_could_leave_the_site_becomes_the_home_page(bad):
    assert _safe_return_path(bad) == "/"


@pytest.mark.parametrize("good", ["/", "/desk", "/app/Customer/CUST-0001?x=1#top", "/a/b%20c", "/%09/still-a-path"])
def test_ordinary_local_paths_are_kept(good):
    assert _safe_return_path(good) == good


# ============================== the browser binding ==============================
class Discovery:
    authorization_endpoint = "https://id.example/authorize"


class Metadata:
    discovery = Discovery()


class FakeClient:
    def load_metadata(self):
        return Metadata()

    def exchange_and_verify(self, **kw):
        return {"issuer": ISSUER, "subject": "sub-1", "email": "a@acme.ng", "name": "A"}


def make_app(tmp_path, secure=False):
    provider = SSOProvider("idp", ISSUER, CLIENT, "https://app.example/sso/idp/callback", frozenset({"id.example"}))
    store = OIDCTransactionStore(tmp_path / "sso.sqlite")
    app = FastAPI()
    app.include_router(create_sso_router(providers={"idp": provider}, transaction_store=store, provider_client_factory=lambda _: FakeClient(), resolve_identity=lambda i, t: "user-1",
                                         issue_session=lambda u, t: "session-token", cookie_secure=secure))
    return app, store


def start(client):
    r = client.get("/sso/idp/login?tenant_id=t1&return_to=%2Fdesk", follow_redirects=False)
    from urllib.parse import parse_qs, urlparse
    return r, parse_qs(urlparse(r.headers["location"]).query)["state"][0]


def test_login_hands_the_browser_a_private_cookie_that_the_callback_requires(tmp_path):
    app, _ = make_app(tmp_path, secure=True)
    r, state = start(TestClient(app))
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{BIND_COOKIE}=") and "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie and "Path=/sso/idp" in cookie and "Max-Age=300" in cookie
    assert state not in cookie                                                                                # the binding is its own secret, not the state


def test_the_browser_that_started_the_login_can_finish_it(tmp_path):
    app, _ = make_app(tmp_path)
    c = TestClient(app, base_url="http://testserver")
    _, state = start(c)
    r = c.get(f"/sso/idp/callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/desk" and "velora_session=session-token" in r.headers["set-cookie"]
    assert any(f"{BIND_COOKIE}=" in h and "Max-Age=0" in h for h in r.headers.get_list("set-cookie"))


def test_a_login_someone_else_started_cannot_be_completed_in_your_browser(tmp_path):
    """Login CSRF: the attacker starts a login and sends the callback link to the victim. Without a binding the victim would be signed in as the ATTACKER."""
    app, _ = make_app(tmp_path)
    attacker, victim = TestClient(app), TestClient(app)
    _, state = start(attacker)
    r = victim.get(f"/sso/idp/callback?code=attackers-code&state={state}", follow_redirects=False)
    assert r.status_code == 401 and "not started in this browser" in r.json()["detail"] and "set-cookie" not in r.headers      # no session was issued
    r2 = attacker.get(f"/sso/idp/callback?code=abc&state={state}", follow_redirects=False)
    assert r2.status_code == 401                                                                                # and the attempt burned the state: guessing is not free


def test_a_wrong_or_missing_binding_cookie_is_refused(tmp_path):
    app, _ = make_app(tmp_path)
    starter, attacker = TestClient(app), TestClient(app)
    _, state = start(starter)
    attacker.cookies.set(BIND_COOKIE, "forged", path="/sso/idp")                                             # a browser that only ever had a guess (it never held the real cookie)
    assert attacker.get(f"/sso/idp/callback?code=abc&state={state}", follow_redirects=False).status_code == 401
    starter, other = TestClient(app), TestClient(app)                                                       # (a browser that has no binding cookie: a fresh client, not cookies.clear(), whose behaviour differs between Starlette versions)
    _, state2 = start(starter)
    assert other.get(f"/sso/idp/callback?code=abc&state={state2}", follow_redirects=False).status_code == 401


# ============================== the store ==============================
def test_a_transaction_can_be_consumed_exactly_once_even_when_callbacks_race(tmp_path):
    store = OIDCTransactionStore(tmp_path / "sso.sqlite")
    store.create(state="the-state", provider="idp", tenant_id="t", nonce="n", verifier="v", return_to="/", binding="b")
    results, gate = [], threading.Barrier(10)

    def attempt():
        gate.wait()
        try:
            store.consume("the-state", provider="idp", binding="b")
            results.append("ok")
        except AuthenticationRequired:
            results.append("refused")
    ts = [threading.Thread(target=attempt) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count("ok") == 1 and results.count("refused") == 9                                          # a SELECT then DELETE let several through


def test_an_expired_transaction_is_refused_and_removed(tmp_path):
    now = [1000.0]
    store = OIDCTransactionStore(tmp_path / "sso.sqlite", clock=lambda: now[0])
    store.create(state="s", provider="idp", tenant_id="t", nonce="n", verifier="v", return_to="/", binding="b", ttl_seconds=60)
    now[0] += 61
    with pytest.raises(AuthenticationRequired, match="invalid, expired or already used"):
        store.consume("s", provider="idp", binding="b")
    now[0] = 1000.0
    with pytest.raises(AuthenticationRequired):
        store.consume("s", provider="idp", binding="b")                                                         # it was taken even though it was expired


def test_a_store_created_before_the_binding_existed_is_upgraded_in_place(tmp_path):
    path = tmp_path / "old.sqlite"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE oidc_transactions (state_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, tenant_id TEXT NOT NULL, nonce TEXT NOT NULL, verifier TEXT NOT NULL,
                   return_to TEXT NOT NULL, expires_at REAL NOT NULL, created_at REAL NOT NULL)""")
    con.commit(); con.close()
    store = OIDCTransactionStore(path)                                                                          # opening it adds the column
    assert "binding_hash" in {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(oidc_transactions)")}
    store.create(state="s", provider="idp", tenant_id="t", nonce="n", verifier="v", return_to="/", binding="b")
    assert store.consume("s", provider="idp", binding="b")["tenant_id"] == "t"
    OIDCTransactionStore(path)                                                                                  # opening it again is harmless


def test_the_binding_is_checked_by_the_store_itself(tmp_path):
    store = OIDCTransactionStore(tmp_path / "sso.sqlite")
    for presented in (None, "", "wrong"):
        store.create(state="s", provider="idp", tenant_id="t", nonce="n", verifier="v", return_to="/", binding="right")
        with pytest.raises(AuthenticationRequired, match="not started in this browser"):
            store.consume("s", provider="idp", binding=presented)
    store.create(state="s", provider="idp", tenant_id="t", nonce="n", verifier="v", return_to="/", binding="right")
    assert store.consume("s", provider="idp", binding="right")
    store.create(state="u", provider="idp", tenant_id="t", nonce="n", verifier="v", return_to="/")             # a transaction made without a binding (by host code) behaves as before
    assert store.consume("u", provider="idp")


# ============================== signing keys ==============================
def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def rs256_token(bits, nonce="nonce-1"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    pub = key.public_key().public_numbers()
    jwks = {"keys": [{"kty": "RSA", "kid": "k1", "use": "sig", "alg": "RS256", "n": b64u(pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")), "e": b64u(pub.e.to_bytes(3, "big"))}]}
    now = int(time.time())
    head = b64u(json.dumps({"alg": "RS256", "kid": "k1", "typ": "JWT"}).encode())
    body = b64u(json.dumps({"iss": ISSUER, "aud": CLIENT, "sub": "s1", "nonce": nonce, "iat": now, "exp": now + 300, "email": "a@acme.ng", "email_verified": True}).encode())
    sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return jwks, f"{head}.{body}.{b64u(sig)}"


def test_a_2048_bit_key_is_accepted_and_a_weaker_one_is_refused():
    jwks, token = rs256_token(2048)
    assert OIDCIDTokenVerifier(ISSUER, CLIENT, jwks).verify(token, expected_nonce="nonce-1")["sub"] == "s1"
    jwks, token = rs256_token(1024)
    with pytest.raises(AuthenticationRequired, match="too small"):
        OIDCIDTokenVerifier(ISSUER, CLIENT, jwks).verify(token, expected_nonce="nonce-1")                        # a perfectly valid signature from a key that can be factored
