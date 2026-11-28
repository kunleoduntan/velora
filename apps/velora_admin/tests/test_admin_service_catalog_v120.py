import json
from pathlib import Path
from fastapi import FastAPI
from velora_admin.api_routes import install_routes

ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = ROOT / "velora_admin" / "administration" / "doctype"

def test_v120_service_and_template_doctypes_are_valid_and_native():
    expected = {
        "service": "Service",
        "service_form_field": "Service Form Field",
        "fulfilment_template": "Fulfilment Template",
        "fulfilment_template_task": "Fulfilment Template Task",
    }
    for folder, name in expected.items():
        data = json.loads((DOCTYPE_ROOT / folder / f"{folder}.json").read_text())
        assert data["name"] == name
        assert "Velora" not in data["name"]
        assert data["module"] == "Administration"
        assert data["fields"]

def test_service_catalog_and_operations_routes_register():
    app = FastAPI()
    install_routes(app, None, lambda request, fn: fn())
    paths = {route.path for route in app.routes}
    assert {
        "/api/admin/services/catalog",
        "/api/admin/services",
        "/api/admin/services/{name}",
        "/api/admin/fulfilment-templates",
        "/api/admin/fulfilment-templates/{name}",
        "/api/admin/service-operations/dashboard",
    }.issubset(paths)


def test_request_and_fulfilment_doctypes_include_service_template_fields():
    req = json.loads((DOCTYPE_ROOT / "request" / "request.json").read_text())
    request_fields = {f["fieldname"] for f in req["fields"]}
    assert {"service", "service_form_data"}.issubset(request_fields)
    task = json.loads((DOCTYPE_ROOT / "request_fulfilment_task" / "request_fulfilment_task.json").read_text())
    task_fields = {f["fieldname"] for f in task["fields"]}
    assert {"depends_on_sequence", "evidence_required", "is_required"}.issubset(task_fields)
