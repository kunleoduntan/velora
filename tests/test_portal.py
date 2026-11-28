"""Company-local customer/supplier portal primitives and public APIs."""
import pytest
from fastapi.testclient import TestClient
from velora.api import create_app
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import Session, session_as
from velora.portal import (authenticate, change_password, create_portal_user, list_submissions, logout, set_portal_user_status,
                           register_public_form, register_resource_provider,
                           resolve_token, submit_public_form)


@pytest.fixture(autouse=True)
def _portal_registries_do_not_leak():
    """PROVIDERS and FORMS are process-wide. A test that registers one (every test runs once per database, in the same process) must not make the next run fail with
    'Portal provider already registered'. The registry itself is right to refuse a different callable under an existing key."""
    from velora import portal
    providers, forms, actions = dict(portal.PROVIDERS), dict(portal.FORMS), dict(portal.ACTIONS)
    portal._FAILS.clear()
    yield
    portal._FAILS.clear()
    portal.ACTIONS.clear(); portal.ACTIONS.update(actions)
    portal.PROVIDERS.clear(); portal.PROVIDERS.update(providers)
    portal.FORMS.clear(); portal.FORMS.update(forms)


def test_portal_account_login_session_and_logout(site):
    created = create_portal_user("Buyer@Example.com", "Buyer One", "a long secure passphrase")
    assert created["email"] == "buyer@example.com"
    result = authenticate("buyer@example.com", "a long secure passphrase")
    assert resolve_token(result["token"])["email"] == "buyer@example.com"
    logout(result["token"])
    with pytest.raises(PermissionDenied):
        resolve_token(result["token"])
    with pytest.raises(PermissionDenied):
        authenticate("buyer@example.com", "incorrect passphrase")


def test_portal_password_and_duplicate_validation(site):
    with pytest.raises(ValidationError):
        create_portal_user("bad-email", "Buyer", "a long secure passphrase")
    create_portal_user("buyer@example.com", "Buyer", "a long secure passphrase")
    with pytest.raises(ValidationError, match="already exists"):
        create_portal_user("buyer@example.com", "Buyer", "another secure passphrase")
    with pytest.raises(ValidationError, match="10 to 256"):
        create_portal_user("short@example.com", "Buyer", "short")


def test_public_form_schema_validation_and_company_local_storage(site):
    register_public_form("contact_us", {"name": {"required": True, "max_length": 80},
        "email": {"type": "email", "required": True}, "message": {"type": "textarea", "max_length": 1000}})
    result = submit_public_form("contact_us", {"name": "Ada", "email": "ADA@example.com", "message": "Hello"}, "127.0.0.1")
    assert result["received"] is True
    with pytest.raises(ValidationError, match="required"):
        submit_public_form("contact_us", {"name": "Ada"})
    with pytest.raises(ValidationError, match="Unexpected"):
        submit_public_form("contact_us", {"name": "Ada", "email": "a@b.com", "admin": True})
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        rows = list_submissions("contact_us")
    assert len(rows) == 1 and rows[0]["payload"]["email"] == "ada@example.com"


def test_portal_http_login_me_logout_and_provider(site):
    create_portal_user("portal@example.com", "Portal User", "a long secure passphrase", ["Customer Portal"])
    register_resource_provider("account.summary", lambda user, params: {"email": user["email"], "period": params.get("period")})
    client = TestClient(create_app(auto_init=False))
    login = client.post("/api/portal/auth/login", json={"email": "portal@example.com", "password": "a long secure passphrase"})
    assert login.status_code == 200 and login.json()["data"]["user"]["email"] == "portal@example.com"
    assert client.get("/api/portal/auth/me").status_code == 200
    data = client.get("/api/portal/resources/account.summary", params={"params": '{"period":"2026"}'}).json()["data"]
    assert data == {"email": "portal@example.com", "period": "2026"}
    assert client.post("/api/portal/auth/logout", json={}).status_code == 200
    assert client.get("/api/portal/auth/me").status_code == 403


def test_portal_password_change_and_suspension_revoke_sessions(site):
    account = create_portal_user("member@example.com", "Member", "a long secure passphrase")
    token = authenticate("member@example.com", "a long secure passphrase")["token"]
    change_password(account["id"], "a long secure passphrase", "a different secure passphrase")
    with pytest.raises(PermissionDenied):
        resolve_token(token)
    assert authenticate("member@example.com", "a different secure passphrase")["user"]["email"] == "member@example.com"
    set_portal_user_status("member@example.com", "suspended")
    with pytest.raises(PermissionDenied):
        authenticate("member@example.com", "a different secure passphrase")


def test_portal_action_route_needs_sign_in_and_runs_the_registered_handler(site):
    from velora.portal import register_action_provider
    create_portal_user("act@example.com", "Act User", "a long secure passphrase", ["Customer Portal"])
    register_action_provider("ticket.raise", lambda user, body: {"by": user["email"], "subject": body.get("subject")})
    client = TestClient(create_app(auto_init=False))
    assert client.post("/api/portal/actions/ticket.raise", json={"subject": "x"}).status_code == 403
    client.post("/api/portal/auth/login", json={"email": "act@example.com", "password": "a long secure passphrase"})
    ok = client.post("/api/portal/actions/ticket.raise", json={"subject": "Late"})
    assert ok.status_code == 200 and ok.json()["data"] == {"by": "act@example.com", "subject": "Late"}
    assert client.post("/api/portal/actions/unknown", json={}).status_code == 404
    with pytest.raises(ValueError):
        register_action_provider("ticket.raise", lambda user, body: {})


def test_portal_sign_in_locks_after_repeated_failures_and_admin_can_set_a_password(site):
    from velora import portal
    from velora.portal import admin_set_password
    create_portal_user("lock@example.com", "Lock User", "a long secure passphrase")
    for _ in range(portal.MAX_FAILS):
        with pytest.raises(PermissionDenied, match="Invalid"):
            authenticate("lock@example.com", "wrong wrong wrong")
    with pytest.raises(PermissionDenied, match="Too many"):
        authenticate("lock@example.com", "a long secure passphrase")
    admin_set_password("lock@example.com", "a brand new passphrase")           # a reset clears the lock
    first = authenticate("lock@example.com", "a brand new passphrase")
    admin_set_password("lock@example.com", "yet another passphrase")           # and ends open sessions
    with pytest.raises(PermissionDenied):
        resolve_token(first["token"])
