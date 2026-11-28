from fastapi import FastAPI
from velora_admin.api_routes import install_routes


def test_admin_approval_and_request_routes_register():
    app=FastAPI()
    install_routes(app, None, lambda request, fn: fn())
    routes={route.path for route in app.routes}
    assert "/api/admin/requests/my" in routes
    assert "/api/admin/requests/{name}" in routes
    assert "/api/admin/requests/{name}/routing-diagnostics" in routes
    assert "/api/admin/approvals/inbox" in routes
    assert "/api/admin/approvals/summary" in routes
    assert "/api/admin/requests/{name}/approve" in routes
    assert "/api/admin/requests/{name}/reject" in routes
