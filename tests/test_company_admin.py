"""Company Administration: create a company with VeloraERP, duplicate it with its setup, grant access with checked roles."""
import pytest

from test_platform import H, PW, clean_state, hdr, login, plat  # noqa: F401  (fixtures)

ERP = ["velora_erp", "velora_projectone"]


def _admin(plat):
    c = plat.client()
    assert login(c, "root@example.com").status_code == 200
    return c


def _erp_ws(plat):
    for a in ERP:
        if a not in plat.ws.apps():
            plat.ws.register_app(a)


@pytest.mark.parametrize("order", [ERP, list(reversed(ERP))])
def test_a_company_with_apps_that_need_each_other_is_created_whatever_the_order(plat, order):
    _erp_ws(plat)
    c = _admin(plat)
    t = plat.plane.registry.list_tenants()[0]["id"]
    r = c.post("/api/platform/companies", headers=H, json={"name": "Gamma " + order[0], "tenant_id": t, "db": "sqlite", "apps": order})
    assert r.status_code == 200, r.text
    co = plat.plane.registry.get_company(r.json()["data"]["id"])
    assert co["status"] == "active"
    assert set(ERP) <= set(plat.plane.router.site_for(co).installed_apps())


def _erp_company(plat, c, name):
    t = plat.plane.registry.list_tenants()[0]["id"]
    r = c.post("/api/platform/companies", headers=H, json={"name": name, "tenant_id": t, "db": "sqlite", "apps": ERP})
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


def test_duplicate_copies_the_chosen_setup_sections_and_a_failed_copy_leaves_nothing_behind(plat, monkeypatch):
    _erp_ws(plat)
    c = _admin(plat)
    src = _erp_company(plat, c, "Source Ltd")
    from velora import new_doc
    with plat.plane.company_scope(src, user_email="Administrator", roles=("System Manager",)):
        g = new_doc("Account Group", group_code="A", group_name="Assets", root_type="Asset", is_group=0).insert(ignore_permissions=True)
        for i in range(25):
            new_doc("Account", account_code=f"1{i:03d}", account_name=f"Cash {i}", account_group=g.name, account_type="CASH").insert(ignore_permissions=True)
    r = c.post(f"/api/platform/companies/{src}/duplicate", headers=H, json={"name": "Copy Ltd", "db": "sqlite", "sections": ["chart_of_accounts"]})
    assert r.status_code == 200, r.text
    new_id = r.json()["data"]["company"]["id"]
    from velora import get_list
    with plat.plane.company_scope(new_id, user_email="Administrator", roles=("System Manager",)):
        assert len(get_list("Account", fields=["name"], limit=100, ignore_permissions=True)) == 25
    # a copy that fails removes the half-made company
    from velora import setup_copy
    from velora.exceptions import ValidationError
    def broken(*a, **k):
        raise ValidationError("Copy stopped at Account: 1 record(s) could not be created")
    monkeypatch.setattr(setup_copy, "apply_bundle", broken)
    before = {x["id"] for x in plat.plane.registry.list_companies()}
    bad = c.post(f"/api/platform/companies/{src}/duplicate", headers=H, json={"name": "Broken Ltd", "db": "sqlite", "sections": ["chart_of_accounts"]})
    assert bad.status_code >= 400
    left = [x for x in plat.plane.registry.list_companies() if x["id"] not in before]
    assert left == [], f"the half-made company must be removed, found {left}"
    assert not [x for x in plat.plane.registry.list_companies() if x["name"] == "Broken Ltd" and x["status"] == "active"]


def test_grant_access_checks_every_role_in_every_company_before_granting_any(plat):
    c = _admin(plat)
    ok = c.post("/api/platform/access/grant", headers=H, json={"email": "carol@example.com", "assignments": [{"company_id": plat.A, "roles": ["Sales User"]}]})
    assert ok.status_code == 200, ok.text
    bad = c.post("/api/platform/access/grant", headers=H, json={"email": "carol@example.com", "assignments": [
        {"company_id": plat.B, "roles": ["Sales User"]}, {"company_id": plat.A, "roles": ["Sales Usr"]}]})
    assert bad.status_code >= 400 and "did you mean 'Sales User'" in bad.json()["message"]
    assert plat.B not in {m["id"] for m in plat.plane.identity.companies_for(plat.plane.identity.get_user("carol@example.com")["id"])}, "nothing granted when one assignment is wrong"
    none = c.post("/api/platform/access/grant", headers=H, json={"email": "nobody@example.com", "assignments": [{"company_id": plat.A, "roles": ["Sales User"]}]})
    assert none.status_code >= 400 and "no user" in none.json()["message"]
