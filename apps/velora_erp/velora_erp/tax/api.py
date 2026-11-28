"""HTTP routes for Tax Management. Every route runs inside the framework's own permission and transaction wrapper."""


def install_routes(app, run):
    from fastapi import Body, Request

    @app.post("/api/tax/calculate")
    def tax_calculate(request: Request, body: dict = Body(default={})):
        def go():
            from velora import throw
            from velora_erp.tax.service import calculate
            b = body or {}
            for k in ("tax_type", "jurisdiction", "amount"):
                if b.get(k) in (None, ""):
                    throw(f"{k} is required.")
            return calculate(b["tax_type"], b["jurisdiction"], b["amount"], b.get("date"), b.get("category"), b.get("tax_inclusive"))
        return run(request, go)

    @app.post("/api/tax/returns/{name}/calculate")
    def tax_return_calculate(name: str, request: Request):
        def go():
            from velora_erp.tax.service import calculate_return
            return calculate_return(name)
        return run(request, go)

    @app.post("/api/tax/returns/{name}/file")
    def tax_return_file(name: str, request: Request, body: dict = Body(default={})):
        def go():
            from velora_erp.tax.service import file_return
            return file_return(name, (body or {}).get("filing_reference", ""))
        return run(request, go)

    @app.post("/api/tax/returns/{name}/outcome")
    def tax_return_outcome(name: str, request: Request, body: dict = Body(default={})):
        def go():
            from velora_erp.tax.service import record_outcome
            return record_outcome(name, bool((body or {}).get("accepted")), (body or {}).get("acknowledgement", ""))
        return run(request, go)

    @app.post("/api/tax/obligations/refresh")
    def tax_obligations_refresh(request: Request):
        def go():
            from velora_erp.tax.service import refresh_obligations
            return {"updated": refresh_obligations()}
        return run(request, go)

    @app.get("/api/tax/catalogue")
    def tax_catalogue(request: Request):
        def go():
            from velora_erp.tax.service import catalogue
            c = catalogue()
            domains: dict = {}
            for r in c:
                d = domains.setdefault(r["domain"], {"domain": r["domain"], "reports": 0, "executable": 0})
                d["reports"] += 1; d["executable"] += 1
            return {"total": len(c), "executable": len(c), "domains": list(domains.values()), "reports": c}
        return run(request, go)

    @app.post("/api/tax/computations/{name}/calculate")
    def tax_computation_calculate(name: str, request: Request):
        def go():
            from velora_erp.tax.cit import calculate_computation
            return calculate_computation(name)
        return run(request, go)

    @app.get("/api/tax/adviser")
    def tax_adviser(request: Request):
        def go():
            from velora_erp.tax.adviser import findings
            return {"findings": findings()}
        return run(request, go)

    @app.get("/api/tax/dashboard")
    def tax_dashboard(request: Request):
        def go():
            from velora_erp.tax.adviser import dashboard
            return dashboard()
        return run(request, go)

    @app.post("/api/print-formats/install-samples")
    def print_samples(request: Request):
        def go():
            from velora_erp.print_samples import install_samples
            return install_samples()
        return run(request, go)
