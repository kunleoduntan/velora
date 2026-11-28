from velora_admin.administration.operations_ui import operations_center_html


def test_operations_center_ui_has_universal_domains():
    html = operations_center_html()
    for domain in ("tasks", "facilities", "work_orders", "vehicles", "trips", "vendors", "supplies", "correspondence", "events", "visitors", "travel", "automation_rules", "knowledge_articles"):
        assert f'value="{domain}"' in html


def test_operations_center_ui_has_quick_actions():
    html = operations_center_html()
    assert "function createTask()" in html
    assert "function processStock()" in html
    assert "function completeTask(name)" in html
    assert "/api/admin/universal/operations-dashboard" in html


def test_operations_center_ui_responsive_and_api_based():
    html = operations_center_html()
    assert "@media(max-width:520px)" in html
    assert "credentials:'same-origin'" in html
    assert "Administration Operations Center" in html


def test_operations_center_ui_route_registered():
    from fastapi import FastAPI
    from velora_admin.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, fn: fn())
    route_paths = {r.path for r in app.routes}
    assert "/api/admin/universal/ui" in route_paths
