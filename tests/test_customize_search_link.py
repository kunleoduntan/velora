"""Customize Form support (insert_after), Frappe-style search_link, and the roles list the workflow builder uses."""
from fastapi.testclient import TestClient

from velora import new_doc
from velora.api import create_app
from velora.api.search import search_link

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
SALES = {"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}


def test_a_custom_field_can_be_placed_after_any_field(site):
    client = TestClient(create_app(auto_init=False))
    base = [f["fieldname"] for f in client.get("/api/meta/Customer", headers=ADMIN).json()["data"]["fields"]]
    anchor = base[0]
    r = client.post("/api/custom-fields/Customer", json={"fieldname": "custom_after", "fieldtype": "Data", "label": "After", "insert_after": anchor}, headers=ADMIN)
    assert r.status_code == 200, r.text
    names = [f["fieldname"] for f in client.get("/api/meta/Customer", headers=ADMIN).json()["data"]["fields"]]
    assert names.index("custom_after") == names.index(anchor) + 1
    bad = client.post("/api/custom-fields/Customer", json={"fieldname": "custom_bad", "fieldtype": "Data", "insert_after": "no_such_field"}, headers=ADMIN)
    assert bad.status_code in (400, 417, 422)


def test_search_link_ranks_exact_then_prefix_then_contains(site):
    new_doc("Customer Group", group_name="Retail").insert()
    for n in ("Zeta Acme", "Acme Traders", "Acme", "Bola Stores"):
        new_doc("Customer", customer_name=n, customer_group="Retail").insert()
    hits = [h["title"] for h in search_link("Customer", "acme")]
    assert hits == ["Acme", "Acme Traders", "Zeta Acme"]                          # exact, then starts-with, then contains
    assert search_link("Customer", "bola")[0]["title"] == "Bola Stores"
    assert not any("Bola" in h for h in hits)
    assert len(search_link("Customer", "", limit=2)) == 2


def test_search_link_route_and_roles(site):
    client = TestClient(create_app(auto_init=False))
    new_doc("Customer Group", group_name="Retail").insert()
    new_doc("Customer", customer_name="Chidi Foods", customer_group="Retail").insert()
    r = client.get("/api/search-link", params={"doctype": "Customer", "txt": "chidi"}, headers=ADMIN)
    assert r.status_code == 200 and any("Chidi" in h["name"] or "Chidi" in (h.get("title") or "") for h in r.json()["data"])
    roles = client.get("/api/roles", headers=ADMIN)
    assert roles.status_code == 200 and "System Manager" in roles.json()["data"]


def test_role_permission_manager_api_supports_docperms_levels_and_field_overrides(site):
    client = TestClient(create_app(auto_init=False))
    created = client.post("/api/role-admin/roles", json={"name": "Project Finance"}, headers=ADMIN)
    assert created.status_code == 200, created.text
    doctype = client.get("/api/role-admin/doctype/Customer", headers=ADMIN)
    assert doctype.status_code == 200 and doctype.json()["data"]["name"] == "Customer"
    for permission in ("read", "report", "export", "import", "email"):
        response = client.post("/api/role-admin/permission", json={
            "role": "Project Finance", "doctype": "Customer", "permission": permission,
            "permlevel": 1, "allowed": True,
        }, headers=ADMIN)
        assert response.status_code == 200, response.text
    access = client.post("/api/role-admin/field-access", json={
        "role": "Project Finance", "doctype": "Customer", "fieldname": "customer_name", "access": "read_only",
    }, headers=ADMIN)
    assert access.status_code == 200, access.text
    effective = client.get("/api/role-admin/role/Project Finance", headers=ADMIN).json()["data"]
    assert any(x["doctype"] == "Customer" and x["permlevel"] == 1 and x["permission"] == "report" and x["allowed"] for x in effective["permissions"])
    assert {"doctype": "Customer", "fieldname": "customer_name", "access": "read_only"} in effective["fields"]
    reset = client.post("/api/role-admin/field-access/reset", json={
        "role": "Project Finance", "doctype": "Customer", "fieldname": "customer_name",
    }, headers=ADMIN)
    assert reset.status_code == 200, reset.text
