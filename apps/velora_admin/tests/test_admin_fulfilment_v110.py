import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTYPES = ROOT / "velora_admin" / "administration" / "doctype"


def _doctype(name):
    return json.loads((DOCTYPES / name / f"{name}.json").read_text())


def test_fulfilment_doctypes_are_native_and_linked():
    assignment = _doctype("request_fulfilment")
    task = _doctype("request_fulfilment_task")
    assert assignment["name"] == "Request Fulfilment"
    assert assignment["istable"] is False
    request_field = next(f for f in assignment["fields"] if f["fieldname"] == "request")
    assert request_field["options"] == "Request"
    assert request_field["unique"] is True
    assert task["istable"] is True
    assert task["name"] == "Request Fulfilment Task"


def test_request_has_fulfilment_tracking_fields():
    request = _doctype("request")
    names = {field["fieldname"] for field in request["fields"]}
    assert {"fulfilment_status", "fulfilment_owner", "fulfilment_due_date"}.issubset(names)


def test_fulfilment_routes_register():
    from fastapi import FastAPI
    from velora_admin.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, fn: fn())
    paths = {route.path for route in app.routes}
    expected = {
        "/api/admin/fulfilment",
        "/api/admin/fulfilment/approved-queue",
        "/api/admin/fulfilment/from-request/{request_name}",
        "/api/admin/fulfilment/{name}/assign",
        "/api/admin/fulfilment/{name}/start",
        "/api/admin/fulfilment/{name}/tasks",
        "/api/admin/fulfilment/{name}/tasks/{task_id}",
        "/api/admin/fulfilment/{name}/complete",
        "/api/admin/fulfilment/{name}/close",
    }
    assert expected.issubset(paths)


def test_fulfilment_status_options_are_valid_json_select_values():
    request = _doctype("request")
    field = next(f for f in request["fields"] if f["fieldname"] == "fulfilment_status")
    assert "\\n" not in field["options"]
    assert "Completed" in field["options"].splitlines()


def test_fulfilment_lifecycle_has_closed_terminal_state():
    assignment = _doctype("request_fulfilment")
    status = next(f for f in assignment["fields"] if f["fieldname"] == "status")
    assert "Closed" in status["options"].splitlines()
    assert {"closed_on", "closure_reason"}.issubset({f["fieldname"] for f in assignment["fields"]})
