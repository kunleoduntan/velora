from fastapi import FastAPI
from velora_admin.api_routes import install_routes


def test_admin_v100_employee_and_configuration_routes_register():
    app = FastAPI()
    install_routes(app, None, lambda request, fn: fn())
    paths = {route.path for route in app.routes}
    expected = {
        "/api/admin/requests/catalog",
        "/api/admin/requests",
        "/api/admin/requests/{name}/submit",
        "/api/admin/analytics",
        "/api/admin/delegations",
        "/api/admin/delegations/{name}",
        "/api/admin/escalation-rules",
        "/api/admin/escalation-rules/{name}",
    }
    assert expected.issubset(paths)


def test_optional_notifications_are_safe_when_notification_log_is_unavailable():
    from velora_admin.administration import approval_service
    approval_service._notify_user("approver@example.test", "Subject", "Message", "AREQ-TEST")
    approval_service._notify_requester(object(), "Subject", "Message")
