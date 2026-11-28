"""HTTP route for the Controls Check screen."""
from fastapi import Request
from velora.meta.registry import registry
from velora.permissions import check_permission
from velora_erp.finance import controls_check as cc


def install_routes(app, scope, run):
    @app.get("/api/controls-check")
    def controls_check(request: Request, from_date: str, to_date: str, scope: str = "Both", stale_days: int = 90):
        def fn():
            check_permission(registry.get("Sales Invoice"), "read")
            check_permission(registry.get("Purchase Invoice"), "read")
            return cc.run_checks(from_date, to_date, scope=scope, stale_days=stale_days)
        return run(request, fn)

    @app.get("/api/gl-review")
    def gl_review(request: Request, from_date: str, to_date: str, prior_from: str, prior_to: str, threshold_pct: float = 50, min_amount: float = 10000):
        def fn():
            from velora_erp.finance import gl_review as glr
            check_permission(registry.get("Account Ledger Record"), "read")
            return glr.run_review(from_date, to_date, prior_from, prior_to, threshold_pct=threshold_pct, min_amount=min_amount)
        return run(request, fn)
