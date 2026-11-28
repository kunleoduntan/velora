"""Theme and report endpoints (installed by create_app with the request scope of the active mode)."""
from __future__ import annotations

from fastapi import Body, FastAPI, Request
from fastapi.responses import Response

from .. import db
from ..exceptions import PermissionDenied, ValidationError
from ..export import XLSX
from ..meta.registry import registry
from ..permissions import get_session
from ..reporting.runner import can_export, can_run, check_report_access, run_adhoc, run_report
from ..reporting.saved import create_saved, delete_saved, export_saved, get_saved, list_saved, run_saved, update_saved, list_versions, restore_version
from ..reporting.service import export_adhoc, export_report
from ..reporting.layouts import list_layouts, get_layout, save_layout, delete_layout, validate_definition, calculate, execute_statement, statement_drilldown, financial_statement_xlsx, financial_statement_pdf
from ..settings import get_setting, set_setting
from ..theme import ThemeSpec, compile_theme, list_presets


def _can_edit_theme() -> bool:
    s = get_session()
    return s.user == "Administrator" or "System Manager" in s.roles


def _xlsx(data: bytes, filename: str) -> Response:
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                                    "Access-Control-Expose-Headers": "Content-Disposition"})


def install_theme_routes(app: FastAPI, scope, run, workspace=None):
    @app.get("/api/theme/public")
    def public_theme():
        """The theme for screens shown BEFORE sign-in (the login page): a workspace-level default, never company data."""
        spec = (workspace.common_config().get("theme") if workspace is not None else None) or {}
        try:
            ct = compile_theme(ThemeSpec.from_dict(spec))
        except Exception:  # noqa: BLE001 - a bad workspace setting must not break the login page
            ct = compile_theme(ThemeSpec())
        return {"data": {"css": ct.css, "default_mode": ct.default_mode, "brand": ct.brand, "spec": ct.spec}}

    @app.get("/api/theme")
    def get_theme(request: Request):
        def fn():
            try:
                spec = ThemeSpec.from_dict(get_setting("theme", {}))
            except Exception:  # noqa: BLE001
                spec = ThemeSpec()
            return {**compile_theme(spec).to_dict(), "presets": list_presets(), "can_edit": _can_edit_theme()}
        return run(request, fn)

    @app.post("/api/theme/preview")
    def preview_theme(request: Request, body: dict = Body(...)):
        def fn():
            if not _can_edit_theme():
                raise PermissionDenied("Only a System Manager can change the theme")
            return compile_theme(ThemeSpec.from_dict(body)).to_dict()
        return run(request, fn)

    @app.put("/api/theme")
    def save_theme(request: Request, body: dict = Body(...)):
        def fn():
            if not _can_edit_theme():
                raise PermissionDenied("Only a System Manager can change the theme")
            spec = ThemeSpec.from_dict(body)                      # validates everything before anything is stored
            ct = compile_theme(spec)
            set_setting("theme", spec.to_dict())
            return {**ct.to_dict(), "presets": list_presets(), "can_edit": True}
        return run(request, fn)


def install_report_routes(app: FastAPI, scope, run):
    @app.get("/api/reports")
    def list_reports(request: Request):
        return run(request, lambda: [{"name": r.name, "module": r.module, "description": r.description, "ref_doctype": r.ref_doctype,
                                      "type": r.type, "can_export": can_export(r)}
                                     for r in sorted(registry.reports(), key=lambda r: (r.module, r.name)) if can_run(r)])

    @app.get("/api/report/{name}")
    def report_definition(name: str, request: Request):
        def fn():
            r = registry.report(name)
            check_report_access(r)
            return {**r.to_dict(), "can_export": can_export(r)}
        return run(request, fn)

    @app.post("/api/report/{name}/run")
    def run_it(name: str, request: Request, body: dict = Body(default={})):
        return run(request, lambda: run_report(name, body.get("filters")).to_dict())

    @app.post("/api/report/{name}/export")
    def export_it(name: str, request: Request, body: dict = Body(default={})):
        with scope(request), db.transaction():
            data, filename = export_report(name, body.get("filters"))
        return _xlsx(data, filename)

    @app.post("/api/adhoc-report/run")
    def adhoc_run(request: Request, body: dict = Body(...)):
        return run(request, lambda: run_adhoc(body).to_dict())

    @app.post("/api/adhoc-report/export")
    def adhoc_export(request: Request, body: dict = Body(...)):
        with scope(request), db.transaction():
            data, filename = export_adhoc(body)
        return _xlsx(data, filename)


    @app.get("/api/saved-reports")
    def saved_list(request: Request):
        return run(request, list_saved)

    @app.post("/api/saved-reports", status_code=201)
    def saved_create(request: Request, body: dict = Body(...)):
        return run(request, lambda: create_saved(body.get("name"), body.get("spec"), bool(body.get("shared"))))

    @app.get("/api/saved-report/{rid}")
    def saved_get(rid: str, request: Request):
        return run(request, lambda: get_saved(rid))

    @app.put("/api/saved-report/{rid}")
    def saved_update(rid: str, request: Request, body: dict = Body(...)):
        return run(request, lambda: update_saved(rid, body.get("name"), body.get("spec"), body.get("shared")))

    @app.get("/api/saved-report/{rid}/versions")
    def saved_report_versions(rid: str, request: Request):
        return run(request, lambda: list_versions(rid))

    @app.post("/api/saved-report/{rid}/versions/{version}/restore")
    def saved_report_restore(rid: str, version: int, request: Request):
        return run(request, lambda: restore_version(rid, version))

    @app.delete("/api/saved-report/{rid}")
    def saved_delete(rid: str, request: Request):
        def fn():
            delete_saved(rid)
            return {"deleted": rid}
        return run(request, fn)

    @app.post("/api/saved-report/{rid}/run")
    def saved_run(rid: str, request: Request):
        return run(request, lambda: run_saved(rid).to_dict())

    @app.post("/api/saved-report/{rid}/export")
    def saved_export(rid: str, request: Request):
        with scope(request), db.transaction():
            data, filename = export_saved(rid)
        return _xlsx(data, filename)


def install_financial_layout_routes(app: FastAPI, scope, run):
    @app.get("/api/financial-report-layouts")
    def financial_layout_list(request: Request):
        return run(request, list_layouts)

    @app.get("/api/financial-report-layout/{lid}")
    def financial_layout_get(lid: str, request: Request):
        return run(request, lambda: get_layout(lid))

    @app.post("/api/financial-report-layouts", status_code=201)
    def financial_layout_create(request: Request, body: dict = Body(...)):
        return run(request, lambda: save_layout(body.get("name"), body.get("definition"), shared=bool(body.get("shared"))))

    @app.put("/api/financial-report-layout/{lid}")
    def financial_layout_update(lid: str, request: Request, body: dict = Body(...)):
        return run(request, lambda: save_layout(body.get("name"), body.get("definition"), lid=lid, shared=bool(body.get("shared"))))

    @app.delete("/api/financial-report-layout/{lid}")
    def financial_layout_delete(lid: str, request: Request):
        return run(request, lambda: delete_layout(lid))

    @app.post("/api/financial-report-layout/validate")
    def financial_layout_validate(request: Request, body: dict = Body(...)):
        return run(request, lambda: validate_definition(body.get("definition")))

    @app.post("/api/financial-report-layout/calculate")
    def financial_layout_calculate(request: Request, body: dict = Body(...)):
        return run(request, lambda: calculate(body.get("definition"), body.get("balances", {}), body.get("periods", {}), body.get("account_attributes", {})))

    @app.post("/api/financial-report/{lid}/run")
    def financial_layout_run(lid: str, request: Request, body: dict = Body(default={})):
        def fn():
            layout = get_layout(lid)
            return execute_statement(layout["definition"], {**(body or {}), "report_name": layout["name"]})
        return run(request, fn)

    @app.post("/api/financial-report/{lid}/drilldown")
    def financial_layout_drilldown(lid: str, request: Request, body: dict = Body(...)):
        def fn():
            layout = get_layout(lid)
            return statement_drilldown(layout["definition"], body.get("filters") or {}, body.get("row_code"), body.get("column_code"), body.get("limit", 500), body.get("account"))
        return run(request, fn)

    @app.get("/api/financial-report/{lid}/export.xlsx")
    def financial_layout_export(lid: str, request: Request):
        with scope(request):
            layout = get_layout(lid)
            filters = {key: request.query_params.get(key) for key in ("from_date", "to_date", "as_of_date", "budget_name", "cost_centre", "branch", "business_unit", "project", "department")}
            result = execute_statement(layout["definition"], filters)
            content = financial_statement_xlsx(result)
            safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in layout["name"]).strip("_")[:80] or "financial_report"
            return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f'attachment; filename="{safe_name}.xlsx"',
                                     "Access-Control-Expose-Headers": "Content-Disposition"})

    @app.get("/api/financial-report/{lid}/export.pdf")
    def financial_layout_export_pdf(lid: str, request: Request):
        with scope(request):
            layout = get_layout(lid)
            filters = {key: request.query_params.get(key) for key in ("from_date", "to_date", "as_of_date", "budget_name", "cost_centre", "branch", "business_unit", "project", "department")}
            result = execute_statement(layout["definition"], filters)
            content = financial_statement_pdf(result)
            safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in layout["name"]).strip("_")[:80] or "financial_report"
            return Response(content, media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"',
                                     "Access-Control-Expose-Headers": "Content-Disposition"})


def install_rule_routes(app: FastAPI, scope, run):
    """Company-local Rule Studio API. Rule definitions are JSON data, never executable code."""
    from ..rules import save_rule, list_rules, get_rule, delete_rule, evaluate_saved_rule, _admin

    @app.get("/api/rules")
    def rule_list(request: Request, scope_name: str | None = None, doctype: str | None = None):
        def fn():
            _admin()
            return list_rules(scope_name, doctype)
        return run(request, fn)

    @app.get("/api/rule/{name}")
    def rule_get(name: str, request: Request):
        def fn():
            _admin()
            return get_rule(name)
        return run(request, fn)

    @app.post("/api/rules", status_code=201)
    def rule_create(request: Request, body: dict = Body(...)):
        return run(request, lambda: save_rule(body))

    @app.put("/api/rule/{name}")
    def rule_update(name: str, request: Request, body: dict = Body(...)):
        def fn():
            if body.get("name") not in (None, name):
                raise ValidationError("Rule name in the payload must match the URL")
            return save_rule({**body, "name": name})
        return run(request, fn)

    @app.delete("/api/rule/{name}")
    def rule_delete(name: str, request: Request):
        return run(request, lambda: delete_rule(name))

    @app.post("/api/rule/{name}/test")
    def rule_test(name: str, request: Request, body: dict = Body(default={})):
        def fn():
            _admin()
            return evaluate_saved_rule(name, body.get("document") or {}, body.get("context") or {})
        return run(request, fn)


def install_policy_governance_routes(app: FastAPI, scope, run):
    """Unified policy governance API; all records are stored in the active company DB."""
    from ..policy_governance import install_routes
    install_routes(app, scope, run)


def install_settings_governance_routes(app: FastAPI, scope, run):
    """Company-local enterprise settings governance API."""
    from ..settings_governance import install_routes
    install_routes(app, scope, run)
