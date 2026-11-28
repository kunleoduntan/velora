from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from velora.controlplane.sso_runtime import OIDCTransactionStore, SSOProvider, create_sso_router
from velora.exceptions import AuthenticationRequired


def test_transaction_is_single_use_and_tenant_bound(tmp_path):
    store = OIDCTransactionStore(tmp_path / "sso.sqlite")
    store.create(state="state-secret", provider="entra", tenant_id="tenant-a", nonce="n",
                 verifier="v", return_to="/desk")
    tx = store.consume("state-secret", provider="entra")
    assert tx["tenant_id"] == "tenant-a"
    assert tx["return_to"] == "/desk"
    with pytest.raises(AuthenticationRequired):
        store.consume("state-secret", provider="entra")
    with pytest.raises(AuthenticationRequired):
        store.consume("state-secret", provider="google")


def test_return_path_rejects_open_redirect(tmp_path):
    store = OIDCTransactionStore(tmp_path / "sso.sqlite")
    store.create(state="s", provider="p", tenant_id="t", nonce="n", verifier="v",
                 return_to="//evil.example")
    assert store.consume("s", provider="p")["return_to"] == "/"


def test_login_redirect_uses_pkce_and_nonce(tmp_path):
    class Discovery:
        authorization_endpoint = "https://id.example/authorize"
    class Metadata:
        discovery = Discovery()
    class Client:
        def load_metadata(self): return Metadata()
    provider = SSOProvider("idp", "https://id.example", "client", "https://app.example/sso/idp/callback",
                           frozenset({"id.example"}))
    store = OIDCTransactionStore(tmp_path / "sso.sqlite")
    app = FastAPI()
    app.include_router(create_sso_router(providers={"idp": provider}, transaction_store=store,
        provider_client_factory=lambda _: Client(), resolve_identity=lambda i, t: "u",
        issue_session=lambda u, t: "token"))
    response = TestClient(app).get("/sso/idp/login?tenant_id=tenant-1&return_to=%2Fdesk", follow_redirects=False)
    assert response.status_code == 302
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"] and params["nonce"] and params["code_challenge"]


def test_callback_resolves_tenant_user_and_sets_http_only_cookie(tmp_path):
    class Discovery:
        authorization_endpoint = "https://id.example/authorize"
    class Metadata:
        discovery = Discovery()
    class Client:
        def load_metadata(self): return Metadata()
        def exchange_and_verify(self, **kwargs):
            assert kwargs["code"] == "auth-code"
            assert kwargs["code_verifier"] == "verifier"
            assert kwargs["nonce"] == "nonce-value"
            return {"issuer": "https://id.example", "subject": "subject-1",
                    "email": "person@example.com", "name": "Person"}
    provider = SSOProvider("idp", "https://id.example", "client", "https://app.example/sso/idp/callback",
                           frozenset({"id.example"}))
    store = OIDCTransactionStore(tmp_path / "sso.sqlite")
    store.create(state="callback-state", provider="idp", tenant_id="tenant-7", nonce="nonce-value",
                 verifier="verifier", return_to="/desk")
    calls = {}
    app = FastAPI()
    app.include_router(create_sso_router(providers={"idp": provider}, transaction_store=store,
        provider_client_factory=lambda _: Client(),
        resolve_identity=lambda identity, tenant: calls.update(identity=identity, tenant=tenant) or "user-7",
        issue_session=lambda user, tenant: f"session:{user}:{tenant}"))
    response = TestClient(app).get("/sso/idp/callback?code=auth-code&state=callback-state", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/desk"
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "secure" in response.headers["set-cookie"].lower()
    assert calls["tenant"] == "tenant-7"
    assert calls["identity"]["subject"] == "subject-1"
