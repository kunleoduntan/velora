"""A company's creator can open it at once, and a person can choose a default company."""
from test_platform import H, PW, clean_state, login, plat  # noqa: F401  (fixtures)


def _admin(plat):
    c = plat.client()
    assert login(c, "root@example.com").status_code == 200
    return c


def _make(plat, name):
    return plat.plane.provisioning.provision_company("Enterprise Group", name, db="sqlite", actor="t")["id"]


def _mine(c):
    return c.get("/api/auth/me", headers=H).json()["data"]


def test_open_gives_the_administrator_access_and_lists_the_company(plat):
    cid = _make(plat, "Second Co")
    c = _admin(plat)
    assert cid not in [x["id"] for x in _mine(c)["companies"]]          # the reported problem: a company you made is not in your list
    r = c.post(f"/api/platform/companies/{cid}/open", headers=H)
    assert r.status_code == 200, r.text
    assert cid in [x["id"] for x in _mine(c)["companies"]]
    assert c.post(f"/api/platform/companies/{cid}/open", headers=H).status_code == 200      # repeating is harmless


def test_open_refuses_a_suspended_or_unknown_company_and_non_admins(plat):
    cid = _make(plat, "Paused Co")
    plat.plane.registry.set_status(cid, "suspended", actor="t")
    c = _admin(plat)
    assert c.post(f"/api/platform/companies/{cid}/open", headers=H).status_code == 422
    assert c.post("/api/platform/companies/NOPE/open", headers=H).status_code == 422
    a = plat.client(); login(a, "alice@example.com")
    assert a.post(f"/api/platform/companies/{plat.A}/open", headers=H).status_code in (401, 403)


def test_default_company_is_saved_cleared_and_needs_access(plat):
    cid = _make(plat, "Third Co")
    c = _admin(plat)
    assert c.post("/api/auth/default-company", headers=H, json={"company_id": cid}).status_code == 403     # no access yet
    c.post(f"/api/platform/companies/{cid}/open", headers=H)
    assert c.post("/api/auth/default-company", headers=H, json={"company_id": cid}).status_code == 200
    assert _mine(c)["default_company"] == cid
    c.post("/api/auth/default-company", headers=H, json={"company_id": ""})
    assert _mine(c)["default_company"] is None


def test_a_company_created_through_the_desk_is_openable_immediately(plat):
    c = _admin(plat)
    tid = plat.plane.registry.list_tenants()[0]["id"]
    r = c.post("/api/platform/companies", headers=H, json={"name": "Made In Desk", "tenant_id": tid, "db": "sqlite"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["id"] in [x["id"] for x in _mine(c)["companies"]]
