"""HTTP routes of the Consolidation Centre: companies I may include, run a consolidation (optionally keeping it), export any view to Excel."""
from fastapi import Body, Request, Response


def install_routes(app, scope, run):
    from velora_erp.finance import consolidation_service as svc

    @app.get("/api/consolidation/companies")
    def consolidation_companies(request: Request):
        return run(request, svc.accessible_companies)

    @app.post("/api/consolidation/run")
    def consolidation_run(request: Request, body: dict = Body(default={})):
        b = body or {}
        return run(request, lambda: svc.run_consolidation(b.get("group"), b.get("from_date"), b.get("to_date"), save=bool(b.get("save"))))

    @app.post("/api/consolidation/export")
    def consolidation_export(request: Request, body: dict = Body(default={})):
        from velora.reporting.excel import report_to_xlsx
        b = body or {}
        with scope(request):
            result = svc.run_consolidation(b.get("group"), b.get("from_date"), b.get("to_date"))
            view = b.get("view") if b.get("view") in ("worksheet", "income", "balance", "checks") else "worksheet"
            content = report_to_xlsx(svc.to_report(result, view))
            name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in f"{result['group']}_{view}_{result['to_date']}").strip("_")[:80] or "consolidation"
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"', "Access-Control-Expose-Headers": "Content-Disposition"})
