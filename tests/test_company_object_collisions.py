import pytest
from fastapi.testclient import TestClient

from velora.api import create_app
from velora.exceptions import MetaError
from velora.meta.registry import registry

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


def _def(name):
    return {"name": name, "module": "Company Custom", "fields": [{"fieldname": "title", "label": "Title", "fieldtype": "Data"}]}


def test_spellings_that_share_a_table_are_refused(site):
    c = TestClient(create_app(auto_init=False))
    assert c.post("/api/devtools/objects", json={"definition": _def("Sales Memo")}, headers=ADMIN).status_code == 200
    for clash in ("Sales-Memo", "sales memo", "Sales  Memo"):
        r = c.post("/api/devtools/objects", json={"definition": _def(clash)}, headers=ADMIN)
        assert r.status_code in (400, 422) and "share its database table" in r.text or "already exists" in r.text, (clash, r.text)
        assert r.status_code != 200, clash


def test_an_archived_object_still_owns_its_table(site):
    c = TestClient(create_app(auto_init=False))
    assert c.post("/api/devtools/objects", json={"definition": _def("Gate Pass")}, headers=ADMIN).status_code == 200
    assert c.delete("/api/devtools/objects/Gate%20Pass", headers=ADMIN).status_code == 200
    r = c.post("/api/devtools/objects", json={"definition": _def("Gate-Pass")}, headers=ADMIN)
    assert r.status_code != 200 and "share its database table" in r.text


def test_collision_helper_ignores_itself_and_the_ignored(site):
    registry.load_company_doctypes([_def("Alpha Note")])
    assert registry.table_collision("Alpha Note") is None
    assert registry.table_collision("Alpha-Note") == "Alpha Note"
    assert registry.table_collision("Alpha-Note", ignore=("Alpha Note",)) is None
    assert registry.table_collision("Alpha_Note", extra_names=("Alpha Note",)) == "Alpha Note"
    registry.load_company_doctypes([])


def test_strict_load_raises_and_changes_nothing(site):
    registry.load_company_doctypes([_def("Beta Note")])
    with pytest.raises(MetaError):
        registry.load_company_doctypes([_def("Gamma Note"), _def("Gamma-Note")])
    assert registry.exists("Beta Note") and not registry.exists("Gamma Note")
    registry.load_company_doctypes([])


def test_tolerant_load_skips_the_bad_object_and_reports_it(site):
    registry.load_company_doctypes([_def("Delta Note"), _def("Delta-Note"), {"name": "Broken", "fields": "nope"}, _def("Fine One")], strict=False)
    assert registry.exists("Delta Note") and registry.exists("Fine One")
    assert not registry.exists("Delta-Note") and not registry.exists("Broken")
    names = {x["name"] for x in registry.company_conflicts}
    assert {"Delta-Note", "Broken"} <= names
    registry.load_company_doctypes([])
    assert registry.company_conflicts == []


def test_list_reports_conflicts(site):
    c = TestClient(create_app(auto_init=False))
    data = c.get("/api/devtools/objects", headers=ADMIN).json()["data"]
    assert data["conflicts"] == []
