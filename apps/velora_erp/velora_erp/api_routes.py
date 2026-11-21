"""One entry point that installs every VeloraERP HTTP route group (hook ``api_routes_provider`` and the entry point)."""


def install_routes(app, scope, run):
    from velora_erp import portal_service
    from velora_erp.finance import bank_reconciliation_api, budget_planner_api, controls_check_api, portal_admin_api
    bank_reconciliation_api.install_routes(app, scope, run)
    budget_planner_api.install_routes(app, scope, run)
    portal_admin_api.install_routes(app, scope, run)
    controls_check_api.install_routes(app, scope, run)
    from velora_erp.investments import api as investment_api
    investment_api.install_investment_routes(app, run)
    from velora_erp.support import api as support_api
    support_api.install_support_routes(app, run)
    portal_service.register()
    from fastapi import Body, Request

    @app.post("/api/inventory/reorder-requests")
    def create_inventory_reorder_requests(request: Request, body: dict = Body(default={})):
        from velora_erp.finance.inventory.requests import create_reorder_requests
        return run(request, lambda: {"requests": create_reorder_requests((body or {}).get("warehouse"))})

    @app.post("/api/hr/workflow-templates/install")
    def install_hr_workflow_templates(request: Request, body: dict = Body(default={})):
        from velora_erp.hr.workflow_templates import install_templates
        return run(request, lambda: install_templates((body or {}).get("doctypes")))

    @app.post("/api/cycle-count/{name}/generate")
    def cycle_count_generate(name: str, request: Request):
        def go():
            from velora import get_doc
            doc = get_doc("Cycle Count", name)
            return {"count": doc.generate_sheet()}
        return run(request, go)

    @app.post("/api/cycle-count/{name}/post")
    def cycle_count_post(name: str, request: Request):
        def go():
            from velora import get_doc
            doc = get_doc("Cycle Count", name)
            return {"stock_reconciliation": doc.post_count()}
        return run(request, go)
