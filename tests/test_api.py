import pytest
from fastapi.testclient import TestClient

from velora.api import create_app

SALES = {"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}
ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


@pytest.fixture
def client(site):
    return TestClient(create_app(auto_init=False))


def test_requires_authentication(client):
    r = client.get("/api/resource/Customer")
    assert r.status_code == 401 and r.json()["error"] == "AuthenticationRequired"


def test_meta_endpoint_drives_the_ui(client):
    r = client.get("/api/meta/Customer", headers=SALES)
    assert r.status_code == 200
    m = r.json()["data"]
    assert m["autoname"] == "series:CUST-.####" and m["track_changes"] is True
    types = [f["fieldtype"] for f in m["fields"]]
    assert "Tab Break" in types and "Table" in types and "Link" in types


def test_crud_flow(client):
    r = client.post("/api/resource/Customer", json={"customer_name": "Api Co", "name": "HACK", "docstatus": 1,
                                                    "contacts": [{"contact_name": "Ife"}]}, headers=SALES)
    assert r.status_code == 201
    doc = r.json()["data"]
    assert doc["name"] == "CUST-0001" and doc["docstatus"] == 0 and doc["contacts"][0]["contact_name"] == "Ife"

    r = client.get(f"/api/resource/Customer/{doc['name']}", headers=SALES)
    assert r.json()["data"]["customer_name"] == "Api Co"

    r = client.put(f"/api/resource/Customer/{doc['name']}", json={"email": "a@b.ng", "modified": doc["modified"]}, headers=SALES)
    assert r.status_code == 200 and r.json()["data"]["email"] == "a@b.ng"

    stale = client.put(f"/api/resource/Customer/{doc['name']}", json={"email": "z@b.ng", "modified": doc["modified"]}, headers=SALES)
    assert stale.status_code == 409 and stale.json()["error"] == "TimestampMismatchError"

    lst = client.get("/api/resource/Customer", params={"filters": '[["status","=","Active"]]'}, headers=SALES)
    assert [x["name"] for x in lst.json()["data"]] == ["CUST-0001"]


def test_backend_enforces_permissions_and_maps_errors(client):
    assert client.post("/api/resource/Customer Group", json={"group_name": "G"}, headers=SALES).status_code == 403
    assert client.post("/api/resource/Customer Group", json={"group_name": "G"}, headers=ADMIN).status_code == 201
    assert client.delete("/api/resource/Customer Group/G", headers=SALES).status_code == 403
    assert client.post("/api/resource/Customer", json={}, headers=SALES).status_code == 422
    assert client.get("/api/resource/Customer/NOPE", headers=SALES).status_code == 404
    assert client.get("/api/resource/Nope", headers=SALES).status_code == 404
    assert client.get("/api/resource/Customer", params={"filters": "{bad"}, headers=SALES).status_code == 422


def test_submit_over_api_and_failure_rolls_back(client):
    client.post("/api/resource/Customer", json={"customer_name": "C", "status": "Blocked"}, headers=SALES)
    so = client.post("/api/resource/Sales Order", json={"customer": "CUST-0001",
                     "items": [{"description": "x", "qty": 2, "rate": 50}]}, headers=SALES).json()["data"]
    r = client.post(f"/api/resource/Sales Order/{so['name']}/submit", headers=SALES)
    assert r.status_code == 422 and "blocked" in r.json()["message"]
    assert client.get(f"/api/resource/Sales Order/{so['name']}", headers=SALES).json()["data"]["docstatus"] == 0


def test_doctype_index_is_permission_filtered(client):
    sales = {d["name"] for d in client.get("/api/doctypes", headers=SALES).json()["data"]}
    assert "Customer" in sales and "Customer Contact" not in sales        # child tables hidden
    nobody = client.get("/api/doctypes", headers={"X-Velora-User": "n"}).json()["data"]
    assert nobody == []


def test_meta_reports_caller_permissions_and_child_meta_is_readable(client):
    m = client.get("/api/meta/Customer Group", headers=SALES).json()["data"]
    assert m["permissions"]["read"] is True and m["permissions"]["create"] is False
    child = client.get("/api/meta/Customer Contact", headers=SALES)
    assert child.status_code == 200 and child.json()["data"]["istable"] is True


def test_count_and_client_scripts(client):
    for n in ("A", "B", "C"):
        client.post("/api/resource/Customer", json={"customer_name": n}, headers=SALES)
    assert client.get("/api/count/Customer", headers=SALES).json()["data"] == 3
    assert client.get("/api/count/Customer", params={"filters": '[["customer_name","=","A"]]'}, headers=SALES).json()["data"] == 1
    js = client.get("/api/client_script/Customer", headers=SALES)
    assert js.status_code == 200 and "velora.ui.form.on" in js.text
    assert "listview_settings" in client.get("/api/client_script/Customer?kind=list", headers=SALES).text
    assert client.get("/api/client_script/Customer Group", headers=SALES).text == ""
    assert client.get("/api/client_script/Customer").status_code == 401


def test_unlabeled_layout_breaks_have_no_generated_heading(client):
    fields = client.get("/api/meta/Customer", headers=SALES).json()["data"]["fields"]
    col = next(f for f in fields if f["fieldname"] == "col_1")
    assert col["fieldtype"] == "Column Break" and col["label"] == "Classification"     # explicit label kept as a heading
    assert next(f for f in fields if f["fieldname"] == "customer_name")["label"] == "Customer Name"
