from fastapi import FastAPI
from velora_admin.api_routes import install_routes


def test_admin_approval_routes_register():
    app = FastAPI()
    install_routes(app, None, lambda request, handler: handler())
    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in app.routes}
    assert ("/api/admin/approvals/inbox", ("GET",)) in routes
    assert ("/api/admin/approvals/summary", ("GET",)) in routes
    assert ("/api/admin/requests/my", ("GET",)) in routes
    assert ("/api/admin/requests/{name}", ("GET",)) in routes
    assert ("/api/admin/requests/{name}/approve", ("POST",)) in routes
    assert ("/api/admin/requests/{name}/reject", ("POST",)) in routes
