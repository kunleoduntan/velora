"""HTTP routes for Debt and Treasury (read-only insight: nothing here posts or changes a record)."""


def install_routes(app, run):
    from fastapi import Request

    @app.get("/api/treasury/dashboard")
    def treasury_dashboard(request: Request):
        def go():
            from velora_erp.treasury.insight import dashboard
            return dashboard()
        return run(request, go)

    @app.get("/api/treasury/liquidity")
    def treasury_liquidity(request: Request, weeks: int = 0):
        def go():
            from velora_erp.treasury.insight import liquidity
            return liquidity(weeks=weeks or None)
        return run(request, go)

    @app.get("/api/treasury/fx")
    def treasury_fx(request: Request):
        def go():
            from velora_erp.treasury.insight import fx_exposure
            return {"rows": fx_exposure()}
        return run(request, go)

    @app.get("/api/treasury/adviser")
    def treasury_adviser(request: Request):
        def go():
            from velora_erp.treasury.insight import adviser
            return {"findings": adviser()}
        return run(request, go)
