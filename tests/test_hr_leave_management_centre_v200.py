from types import SimpleNamespace


def test_hr_leave_preview_route_is_registered():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app = FastAPI()
    install_hr_routes(app, lambda request, fn: {"data": fn()})
    assert any(route.path == "/api/hr/leave-policy/preview" and "POST" in route.methods for route in app.routes)


def test_leave_preview_access_allows_hr_operations_roles(monkeypatch):
    import velora.api.hr as hr
    monkeypatch.setattr(hr, "get_session", lambda: SimpleNamespace(user="hr.officer", roles=["HR Officer"]))
    hr._require_hr_preview_access()


def test_leave_preview_access_rejects_non_hr_roles(monkeypatch):
    import pytest
    import velora.api.hr as hr
    from velora.exceptions import PermissionDenied
    monkeypatch.setattr(hr, "get_session", lambda: SimpleNamespace(user="staff", roles=["Employee"]))
    with pytest.raises(PermissionDenied):
        hr._require_hr_preview_access()


def test_workspace_accepts_leave_management_centre_shortcut():
    from velora.application_workspaces import _clean_widget
    widget = _clean_widget({"type": "shortcut", "title": "Leave Management Centre", "route": "#/hr/leave", "width": 4})
    assert widget["route"] == "#/hr/leave"
