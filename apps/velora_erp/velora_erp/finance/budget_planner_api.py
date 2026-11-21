"""HTTP routes for the Budget Workbench."""
from fastapi import Body, Request
from velora.meta.registry import registry
from velora.permissions import check_permission
from velora_erp.finance import budget_planner as bp


def _can(ptype):
    check_permission(registry.get("Financial Budget"), ptype)


def install_routes(app, scope, run):
    base = "/api/budget-planner"

    @app.get(f"{base}/workbench")
    def workbench(budget: str, request: Request, through_month: int | None = None):
        def fn():
            _can("read")
            return bp.workbench(budget, through_month)
        return run(request, fn)

    @app.post(f"{base}/propose")
    def propose(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return {"rows": bp.propose_plan(body.get("financial_year"), method=body.get("method") or "Historical Pattern",
                                            growth_percent=body.get("growth_percent") or 0,
                                            root_types=tuple(body.get("root_types") or ("Expense",)))}
        return run(request, fn)

    @app.post(f"{base}/project")
    def project(request: Request, body: dict = Body(...)):
        def fn():
            _can("write")
            return {"rows": bp.project_rows(body.get("financial_year"), body.get("rows") or [], method=body.get("method") or "Historical Pattern",
                                            growth_percent=body.get("growth_percent") or 0)}
        return run(request, fn)

    @app.post(f"{base}/allocate-preview")
    def allocate_preview(request: Request, body: dict = Body(...)):
        def fn():
            _can("read")
            dimension = "branch" if body.get("allocate_by") == "Branch" else "cost_centre"
            return {"rows": bp.allocation_table(body.get("allocations") or [], body.get("method") or "Equal", body.get("total") or 0, dimension=dimension)}
        return run(request, fn)
