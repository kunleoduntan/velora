"""Standard password policy, temporary passwords, forgot-password (email link or administrator), and the must-change gate."""
import pytest
from fastapi.testclient import TestClient

from velora.api import create_app
from velora.controlplane import ControlPlane
from velora.controlplane.passwords import check_strength, temporary_password
from velora.exceptions import CompanyAccessDenied, ValidationError
from velora.workspace import Workspace

PW = "long secure password"
H = {"X-Velora-Request": "1"}


@pytest.fixture
def plane(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    p = ControlPlane.create(Workspace.create(tmp_path / "ws"), admin_email="boss@example.com", admin_password=PW)
    p.identity.create_user("ada@example.com", "Ada", "Ada-pass-2026")
    yield p
    p.dispose()


def client(plane):
    return TestClient(create_app(auto_init=False, workspace=plane.ws, plane=plane))


def uid(plane, email):
    return plane.identity.get_user(email)["id"]


def admin_ctx(plane):
    return plane.identity.authenticate("boss@example.com", PW).context


def test_policy_is_one_standard_everywhere():
    for bad in ("short1", "alllowercase", "1234567890", "password", "ada@example.com", "aaaaaaaaaa1"):
        with pytest.raises(ValidationError):
            check_strength(bad, "ada@example.com")
    check_strength("Tulip-7-garden", "ada@example.com")
    check_strength("a long passphrase of words", "ada@example.com")
    for _ in range(50):
        check_strength(temporary_password())


def test_admin_issues_temporary_password_and_it_must_be_changed(plane):
    with pytest.raises(CompanyAccessDenied):
        plane.passwords.issue_temporary(plane.identity.authenticate("ada@example.com", "Ada-pass-2026").context, uid(plane, "ada@example.com"))
    out = plane.passwords.issue_temporary(admin_ctx(plane), uid(plane, "ada@example.com"))
    temp = out["temporary_password"]
    with pytest.raises(Exception):
        plane.identity.authenticate("ada@example.com", "Ada-pass-2026")                 # the old password is gone
    c = client(plane)
    r = c.post("/api/auth/login", json={"email": "ada@example.com", "password": temp})
    assert r.status_code == 200 and r.json()["data"]["force_change"] is True
    assert c.get("/api/platform/companies").status_code == 403                          # blocked until the password is changed
    assert c.get("/api/platform/companies").json()["error"] == "PasswordChangeRequired"
    assert c.get("/api/auth/me").status_code == 200
    r = c.post("/api/auth/change-password", json={"current_password": temp, "new_password": "weak"}, headers=H)
    assert r.status_code in (400, 422)
    r = c.post("/api/auth/change-password", json={"current_password": temp, "new_password": "Brand-new-pass-77"}, headers=H)
    assert r.status_code == 200
    r = c.post("/api/auth/login", json={"email": "ada@example.com", "password": "Brand-new-pass-77"})
    assert r.json()["data"]["force_change"] is False


def test_forgot_password_without_mail_waits_for_the_administrator(plane):
    c = client(plane)
    a = c.post("/api/auth/forgot-password", json={"email": "ada@example.com"}).json()["data"]
    b = c.post("/api/auth/forgot-password", json={"email": "nobody@example.com"}).json()["data"]
    assert a == b and a["mode"] == "administrator"                                       # identical answer: no account discovery
    admin = admin_ctx(plane)
    pending = plane.passwords.pending_requests(admin)
    assert [p["email"] for p in pending] == ["ada@example.com"]
    out = plane.passwords.issue_temporary(admin, pending[0]["user_id"])
    assert plane.passwords.pending_requests(admin) == []
    assert plane.identity.authenticate("ada@example.com", out["temporary_password"]).context.email == "ada@example.com"


def test_forgot_password_with_mail_sends_a_one_time_link(plane, monkeypatch):
    plane.ws.update_config(email={"host": "smtp.example.com", "from_addr": "no-reply@example.com"})
    sent = []
    import velora_notify.channels as ch
    monkeypatch.setattr(ch, "send_email", lambda d, cfg=None: sent.append(d))
    c = client(plane)
    assert c.post("/api/auth/forgot-password", json={"email": "ada@example.com"}).json()["data"]["mode"] == "email"
    assert len(sent) == 1 and "temporary" not in sent[0]["body"].lower()
    token = sent[0]["body"].split("token=")[1].split()[0]
    assert plane.passwords.pending_requests(admin_ctx(plane)) == []
    assert c.post("/api/auth/reset-password", json={"token": token, "new_password": "weak"}).status_code in (400, 422)
    assert c.post("/api/auth/reset-password", json={"token": token, "new_password": "Fresh-secret-4411"}).status_code == 200
    assert plane.identity.authenticate("ada@example.com", "Fresh-secret-4411")
    assert c.post("/api/auth/reset-password", json={"token": token, "new_password": "Another-secret-55"}).status_code in (400, 422)   # once only


def test_requests_are_throttled_and_mail_failure_falls_back_to_the_administrator(plane, monkeypatch):
    plane.ws.update_config(email={"host": "smtp.example.com", "from_addr": "no-reply@example.com"})
    import velora_notify.channels as ch
    def boom(*a, **k): raise RuntimeError("smtp down")
    monkeypatch.setattr(ch, "send_email", boom)
    c = client(plane)
    for _ in range(6):
        c.post("/api/auth/forgot-password", json={"email": "ada@example.com"})
    assert len(plane.passwords.pending_requests(admin_ctx(plane))) == 1                  # failed mail -> waits for an administrator; spam is capped


def test_creating_a_user_can_hand_over_a_first_password(plane):
    c = client(plane)
    c.post("/api/auth/login", json={"email": "boss@example.com", "password": PW})
    r = c.post("/api/platform/users", json={"email": "new@example.com", "full_name": "New Person", "issue_temporary_password": True}, headers=H)
    assert r.status_code == 200 and r.json()["data"]["temporary_password"]
    assert plane.identity.authenticate("new@example.com", r.json()["data"]["temporary_password"]).context.email == "new@example.com"
