"""Each company chooses how dates and numbers are shown; only a System Manager may change it."""
from test_platform import H, PW, clean_state, hdr, login, plat  # noqa: F401  (fixtures)


def test_default_then_change_then_per_company(plat):
    a = plat.client()
    login(a, "alice@example.com")
    cur = a.get("/api/display-format", headers=hdr(plat.A)).json()["data"]
    assert cur["date"] == "YYYY-MM-DD" and cur["number"] == "1,234.56" and len(cur["dates"]) == 5
    r = a.put("/api/display-format", json={"date": "DD/MM/YYYY", "number": "1.234,56"}, headers=hdr(plat.A))
    assert r.status_code == 200 and r.json()["data"]["date"] == "DD/MM/YYYY"
    assert a.get("/api/display-format", headers=hdr(plat.A)).json()["data"]["number"] == "1.234,56"
    bad = a.put("/api/display-format", json={"date": "31st of Dec", "number": "1,234.56"}, headers=hdr(plat.A))
    assert bad.status_code in (400, 422)
    b = plat.client()                                                              # bob's company is a different database
    login(b, "bob@example.com")
    assert b.get("/api/display-format", headers=hdr(plat.B)).json()["data"]["date"] == "YYYY-MM-DD"


def test_only_a_system_manager_may_change_it(plat):
    c = plat.client()
    login(c, "alice@example.com")
    assert c.put("/api/display-format", json={"date": "DD/MM/YYYY", "number": "1,234.56"}, headers=hdr(plat.B)).status_code == 403          # only a Sales User there
