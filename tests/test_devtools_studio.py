from velora.devtools.studio import catalog, inspect_doctype


def test_developer_catalog_lists_installed_apps_and_doctypes(site):
    result = catalog()
    assert result["doctype_count"] >= 1
    assert any(app["name"] == "velora_demo" for app in result["apps"])
    assert isinstance(result["doc_events"], list)
    assert isinstance(result["job_handlers"], list)


def test_doctype_inspection_exposes_metadata_and_generic_api(site):
    result = inspect_doctype("Customer")
    assert result["name"] == "Customer"
    assert result["app"] == "velora_demo"
    assert "fields" in result and isinstance(result["fields"], list)
    assert result["api"]["create"] == "POST /api/resource/Customer"
    assert result["api"]["metadata"] == "GET /api/meta/Customer"


def test_developer_studio_routes_are_system_manager_only(site):
    from fastapi.testclient import TestClient
    from velora.api import create_app
    client = TestClient(create_app(auto_init=False))
    admin = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
    ordinary = {"X-Velora-User": "reader", "X-Velora-Roles": "Sales User"}
    catalog_response = client.get("/api/devtools/catalog", headers=admin)
    assert catalog_response.status_code == 200
    assert catalog_response.json()["data"]["doctype_count"] >= 1
    inspect_response = client.get("/api/devtools/doctype/Customer", headers=admin)
    assert inspect_response.status_code == 200
    assert inspect_response.json()["data"]["api"]["create"] == "POST /api/resource/Customer"
    assert client.get("/api/devtools/catalog", headers=ordinary).status_code == 403
