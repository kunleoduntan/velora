"""Regression tests for defects found in the independent v1.4.0 review."""
import re

import pytest
from fastapi.testclient import TestClient

import velora
from velora.exceptions import PermissionDenied, ValidationError


@pytest.fixture()
def app_client(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'review.db'}", apps=[], developer_mode=True)
    velora.init()
    velora.migrate()
    from velora.api.app import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


def test_ai_routes_do_not_demand_a_request_query_parameter(app_client):
    """`Request` was imported inside install_routes(); with deferred annotations FastAPI then made `request` a required query parameter (HTTP 422 on all 29 AI routes)."""
    for path in ("/api/ai/capabilities", "/api/ai/providers", "/api/ai/developer/tools"):
        r = app_client.get(path)
        assert r.status_code != 422, (path, r.text)
        assert r.status_code in (401, 403), (path, r.status_code)


def test_openapi_document_builds(app_client):
    r = app_client.get("/openapi.json")
    assert r.status_code == 200
    assert not [p for p, ops in r.json()["paths"].items() for o in ops.values()
                if any(x.get("name") == "request" and x.get("in") == "query" for x in o.get("parameters", []))]


@pytest.mark.parametrize("kwargs", [
    {"doctype": ["x"]}, {"doctype": 5}, {"doctype": " "},
])
def test_ai_database_query_rejects_non_text_doctype(kwargs, app_client):
    from velora.ai_developer import query_database
    with pytest.raises(ValidationError):
        query_database(**kwargs)


@pytest.mark.parametrize("filters", [[[["a"], "=", 1]], [["f", ["="], 1]], [["only-two", "="]], [{"a": 1}], {1: "x"}])
def test_ai_database_query_rejects_malformed_filters(filters, tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'q.db'}", apps=["velora_demo"], developer_mode=True)
    velora.init(); velora.migrate()
    from velora.ai_developer import query_database
    with pytest.raises(ValidationError):
        query_database("Customer", filters=filters)


def test_permission_lookup_fails_closed_on_unexpected_database_errors(tmp_path, monkeypatch):
    """A deny rule that cannot be READ must never degrade into the metadata default (allow)."""
    velora.configure(db_url=f"sqlite:///{tmp_path / 'p.db'}", apps=[], developer_mode=True)
    velora.init(); velora.migrate()
    from velora import db, permissions as perm

    class Boom(Exception):
        pass

    real = db.transaction

    def broken(*a, **k):
        raise Boom("statement timeout")
    monkeypatch.setattr(db, "transaction", broken)
    with pytest.raises(PermissionDenied):
        perm._policy_decision("Customer", "write", {"Sales User"})
    with pytest.raises(PermissionDenied):
        perm.field_access("Customer", "credit_limit", perm.Session("u@x.test", frozenset({"Sales User"})))
    with pytest.raises(PermissionDenied):
        perm._effective_roles(perm.Session("u@x.test", frozenset({"Sales User"})))
    monkeypatch.setattr(db, "transaction", real)


def test_permission_lookup_still_tolerates_an_unmigrated_database(monkeypatch):
    from velora import db, permissions as perm

    def missing(*a, **k):
        raise RuntimeError("no such table: velora_role_permission")
    monkeypatch.setattr(db, "transaction", missing)
    assert perm._policy_decision("Customer", "write", {"Sales User"}) is None
    assert perm.field_access("Customer", "x", perm.Session("u@x.test", frozenset({"Sales User"}))) == "editable"


def test_every_engine_module_with_tables_is_in_the_migration_registry():
    from velora.db import extra_tables
    owners = {m for m, _ in extra_tables.OWNERS}
    for mod in ("velora.ai_tool_engine", "velora.ai_migrations", "velora.ai_developer", "velora.ai_app_builder", "velora.document.recycle_bin"):
        assert mod in owners


def test_workspace_shortcuts_cannot_point_at_administrative_settings_pages():
    from velora.application_workspaces import _clean_widget
    for page in ("security", "doctype-creator", "developer-studio", "object-manager"):
        with pytest.raises(ValidationError):
            _clean_widget({"type": "shortcut", "title": "x", "route": f"#/settings/{page}"})
    assert _clean_widget({"type": "shortcut", "title": "x", "route": "#/settings/company-setup"})["route"] == "#/settings/company-setup"
