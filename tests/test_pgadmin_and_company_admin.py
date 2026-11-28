"""The PostgreSQL administrator login is found by itself (so the Desk never asks for it), and companies can be suspended, activated and deleted from the Desk."""
import json

import pytest

from velora import pgadmin
from velora.controlplane import ControlPlane  # noqa: F401
from test_platform import H, PW, clean_state, login, plat  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    for k in ("VELORA_DB_ROOT_USER", "VELORA_DB_ROOT_PASSWORD"):
        monkeypatch.delenv(k, raising=False)


def test_nothing_configured_means_no_login(tmp_path):
    ws = tmp_path / "srv" / "workspace"
    ws.mkdir(parents=True)
    assert pgadmin.resolve(ws) == ("postgres", None, "none")
    assert pgadmin.status(ws) == {"configured": False, "user": "postgres", "source": "none"}


def test_the_installers_password_file_is_found(tmp_path):
    ws = tmp_path / "srv" / "workspace"
    ws.mkdir(parents=True)
    (tmp_path / "srv" / ".db-root-password").write_text("s3cret\n")
    assert pgadmin.resolve(ws) == ("velora_root", "s3cret", "installer")


def test_precedence_given_then_environment_then_config_then_installer(tmp_path, monkeypatch):
    ws = tmp_path / "srv" / "workspace"
    (ws / "config").mkdir(parents=True)
    (tmp_path / "srv" / ".db-root-password").write_text("installer-pw")
    pw = tmp_path / "other-pw"
    pw.write_text("config-pw")
    pgadmin.save(ws, "cfg_user", str(pw))
    assert pgadmin.resolve(ws) == ("cfg_user", "config-pw", "config")
    monkeypatch.setenv("VELORA_DB_ROOT_PASSWORD", "env-pw")
    assert pgadmin.resolve(ws) == ("cfg_user", "env-pw", "environment")
    assert pgadmin.resolve(ws, "me", "typed") == ("me", "typed", "given")


def test_the_password_is_never_written_into_the_workspace_config(tmp_path):
    ws = tmp_path / "w"
    ws.mkdir()
    pw = tmp_path / "pw"
    pw.write_text("topsecret")
    pgadmin.save(ws, "velora_root", str(pw))
    text = (ws / "config" / "common.json").read_text()
    assert "topsecret" not in text and json.loads(text)["pg_admin"]["password_file"] == str(pw)


def test_save_refuses_an_unreadable_password_file(tmp_path):
    with pytest.raises(ValueError):
        pgadmin.save(tmp_path, "velora_root", str(tmp_path / "missing"))


def test_status_endpoint_never_returns_the_password(plat, monkeypatch):
    monkeypatch.setenv("VELORA_DB_ROOT_PASSWORD", "very-secret-pw")
    plat.plane.identity.create_user("root2@example.com", "Root", PW)
    c = plat.client()
    assert login(c, "root@example.com").status_code == 200
    r = c.get("/api/platform/pg-admin", headers=H)
    assert r.status_code == 200 and r.json()["data"]["configured"] is True
    assert "very-secret-pw" not in r.text


def test_company_list_hides_the_secret_reference(plat):
    c = plat.client()
    login(c, "root@example.com")
    rows = c.get("/api/platform/companies", headers=H).json()["data"]
    assert rows and all("secret_ref" not in r for r in rows)
    assert all("provisioning_error" in r for r in rows)


def test_suspend_and_activate_from_the_desk(plat):
    c = plat.client()
    login(c, "root@example.com")
    assert c.post(f"/api/platform/companies/{plat.B}/status", json={"status": "suspended"}, headers=H).status_code == 200
    assert plat.plane.registry.get_company(plat.B)["status"] == "suspended"
    assert c.post(f"/api/platform/companies/{plat.B}/status", json={"status": "active"}, headers=H).status_code == 200
    assert c.post(f"/api/platform/companies/{plat.B}/status", json={"status": "bogus"}, headers=H).status_code in (400, 422)


def test_delete_needs_the_exact_name_and_non_admins_are_refused(plat):
    c = plat.client()
    login(c, "alice@example.com")
    assert c.request("DELETE", f"/api/platform/companies/{plat.B}", json={"confirm": "Value Impacts Consulting"}, headers=H).status_code in (401, 403)   # not a platform admin
    c = plat.client()
    login(c, "root@example.com")
    wrong = c.request("DELETE", f"/api/platform/companies/{plat.B}", json={"confirm": "value impacts"}, headers=H)
    assert wrong.status_code in (400, 422) and plat.plane.registry.get_company(plat.B)
    none = c.request("DELETE", f"/api/platform/companies/{plat.B}", headers=H)
    assert none.status_code in (400, 422) and plat.plane.registry.get_company(plat.B)


def test_delete_removes_the_company(plat):
    c = plat.client()
    login(c, "root@example.com")
    r = c.request("DELETE", f"/api/platform/companies/{plat.B}", json={"confirm": "Value Impacts Consulting"}, headers=H)
    assert r.status_code == 200, r.text
    assert plat.plane.registry.get_company(plat.B) is None
    assert plat.plane.registry.get_company(plat.A)


def test_the_last_active_company_cannot_be_deleted(plat):
    plat.plane.registry.set_status(plat.B, "suspended")
    c = plat.client()
    login(c, "root@example.com")
    r = c.request("DELETE", f"/api/platform/companies/{plat.A}", json={"confirm": "Velora Technologies"}, headers=H)
    assert r.status_code in (400, 422) and plat.plane.registry.get_company(plat.A)
