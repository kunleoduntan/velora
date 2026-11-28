"""People & Access: one step to add a person with the right roles, checked roles, safe limits for a company's own System Manager."""
import pytest

from test_platform import PW, clean_state, hdr, login, plat  # noqa: F401  (fixtures)


def _as(plat, email="alice@example.com"):
    c = plat.client()
    assert login(c, email=email).status_code == 200
    return c


def test_a_company_system_manager_adds_a_person_in_one_step_and_they_can_sign_in(plat):
    c = _as(plat)                                                      # alice is System Manager of A
    opts = c.get("/api/people/options", headers=hdr(plat.A)).json()["data"]
    assert "Sales User" in {r["name"] for r in opts["roles"]} and any(p["roles"] == ["System Manager"] for p in opts["profiles"])
    r = c.post("/api/people", headers=hdr(plat.A), json={"email": "Dan@Example.com", "full_name": "Dan", "roles": ["Sales User"]})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["email"] == "dan@example.com" and d["new_user"] and d["temporary_password"] and r.headers["cache-control"] == "no-store"
    listed = {p["email"]: p for p in c.get("/api/people", headers=hdr(plat.A)).json()["data"]}
    assert listed["dan@example.com"]["roles"] == ["Sales User"]
    dan = plat.client()
    assert login(dan, email="dan@example.com", pw=d["temporary_password"]).status_code == 200
    prof = dan.get("/api/auth/me", headers=hdr(plat.A))
    assert prof.status_code == 200


def test_a_typo_in_a_role_is_refused_with_a_suggestion(plat):
    c = _as(plat)
    r = c.post("/api/people", headers=hdr(plat.A), json={"email": "eve@example.com", "roles": ["Sales Usr"]})
    assert r.status_code >= 400
    j = r.json()
    assert "did you mean 'Sales User'" in j["message"] and j["advice"]["field"] == "roles"
    assert plat.plane.identity.get_user("eve@example.com") is None, "nothing is created when the roles are wrong"


def test_an_existing_sign_in_is_given_access_without_a_new_password(plat):
    c = _as(plat)
    r = c.post("/api/people", headers=hdr(plat.A), json={"email": "carol@example.com", "roles": ["Sales User"]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["new_user"] is False and r.json()["data"]["temporary_password"] is None, "a company admin never resets someone's existing password"
    again = c.post("/api/people", headers=hdr(plat.A), json={"email": "carol@example.com", "roles": ["Sales User"]})
    assert again.status_code >= 400 and "already works in this company" in again.json()["message"]


def test_a_company_admin_cannot_manage_another_company_or_remove_the_last_system_manager(plat):
    c = _as(plat)                                                      # alice: System Manager in A, only Sales User in B
    assert c.post("/api/people", headers=hdr(plat.B), json={"email": "x@example.com", "roles": ["Sales User"]}).status_code == 403
    r = c.post("/api/people/alice@example.com/roles", headers=hdr(plat.A), json={"roles": ["Sales User"]})
    assert r.status_code >= 400 and "only System Manager" in r.json()["message"]
    assert c.delete("/api/people/alice@example.com", headers=hdr(plat.A)).status_code >= 400
    seller = _as(plat, "bob@example.com")                             # bob is System Manager of B but has no access to A at all
    assert seller.get("/api/people", headers=hdr(plat.A)).status_code in (401, 403)


def test_changing_and_removing_roles_takes_effect_in_the_company_database(plat):
    c = _as(plat)
    c.post("/api/people", headers=hdr(plat.A), json={"email": "fay@example.com", "roles": ["Sales User"]})
    assert c.post("/api/people/fay@example.com/roles", headers=hdr(plat.A), json={"roles": ["Sales User", "System Manager"]}).status_code == 200
    company = plat.plane.registry.get_company(plat.A)
    assert sorted(plat.plane.identity._company_roles(company, [], user_email="fay@example.com")) == ["Sales User", "System Manager"]
    assert c.delete("/api/people/fay@example.com", headers=hdr(plat.A)).status_code == 200
    assert plat.plane.identity._company_roles(company, [], user_email="fay@example.com") == [], "removed means no roles left behind"


def test_the_platform_admin_membership_screen_now_writes_roles_where_sign_in_reads_them(plat):
    """Before 1.19.0 the platform screen wrote roles only to the control-plane index, which sign-in ignores once a company row exists."""
    from types import SimpleNamespace
    from velora.controlplane.user_admin import UserAdministration
    admin = SimpleNamespace(is_platform_admin=True, email="root@example.com")
    ua = UserAdministration(plat.plane)
    carol = plat.plane.identity.get_user("carol@example.com")
    ua.grant_company_membership(admin, carol["id"], plat.A, ["Sales User"])
    company = plat.plane.registry.get_company(plat.A)
    assert plat.plane.identity._company_roles(company, [], user_email="carol@example.com") == ["Sales User"]
    ua.grant_company_membership(admin, carol["id"], plat.A, ["System Manager"])          # a change after the first grant
    assert plat.plane.identity._company_roles(company, [], user_email="carol@example.com") == ["System Manager"]
    ua.revoke_company_membership(admin, carol["id"], plat.A)
    assert plat.plane.identity._company_roles(company, [], user_email="carol@example.com") == []
