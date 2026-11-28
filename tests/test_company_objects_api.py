from fastapi.testclient import TestClient

from velora.api import create_app

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


def test_company_object_manager_create_edit_archive_restore(site):
    client = TestClient(create_app(auto_init=False))
    definition = {
        "name": "Company Asset Card", "module": "Company Custom", "fields": [
            {"fieldname": "asset_title", "label": "Asset Title", "fieldtype": "Data", "required": True},
        ],
    }
    created = client.post("/api/devtools/objects", json={"definition": definition}, headers=ADMIN)
    assert created.status_code == 200, created.text
    assert created.json()["data"]["created"] == "Company Asset Card"

    listed = client.get("/api/devtools/objects", headers=ADMIN)
    assert listed.status_code == 200
    assert any(x["name"] == "Company Asset Card" for x in listed.json()["data"]["objects"])

    updated_definition = {**definition, "fields": definition["fields"] + [
        {"fieldname": "asset_location", "label": "Asset Location", "fieldtype": "Data"},
    ]}
    updated = client.put("/api/devtools/objects/Company%20Asset%20Card", json={"definition": updated_definition}, headers=ADMIN)
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["updated"] == "Company Asset Card"

    archived = client.delete("/api/devtools/objects/Company%20Asset%20Card", headers=ADMIN)
    assert archived.status_code == 200, archived.text
    assert archived.json()["data"]["deleted"] == "Company Asset Card"
    assert not any(x["name"] == "Company Asset Card" for x in client.get("/api/devtools/objects", headers=ADMIN).json()["data"]["objects"])

    restored = client.post("/api/devtools/objects/Company%20Asset%20Card/restore", headers=ADMIN)
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["restored"] == "Company Asset Card"
    assert any(x["name"] == "Company Asset Card" for x in client.get("/api/devtools/objects", headers=ADMIN).json()["data"]["objects"])
