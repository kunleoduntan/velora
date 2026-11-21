"""Generic REST API. One set of routes serves every DocType.

  GET    /api/meta/{doctype}
  GET    /api/resource/{doctype}?filters=[..]&fields=[..]&order_by=..&limit=..&offset=..
  POST   /api/resource/{doctype}
  GET    /api/resource/{doctype}/{name}
  PUT    /api/resource/{doctype}/{name}          (send `modified` back for optimistic locking)
  DELETE /api/resource/{doctype}/{name}
  POST   /api/resource/{doctype}/{name}/submit | cancel

Authentication is a placeholder until the Security phase: in developer mode the
caller identifies itself with X-Velora-User / X-Velora-Roles headers. Outside
developer mode every request is rejected - there is no silent open default.
Permissions are enforced inside the Document engine, not here.
"""
import json
import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from sqlalchemy.exc import DataError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from fastapi import Body, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import db, runtime
from .. import site as site_mod
from ..bulk import bulk_action
from ..document import get_aggregate, get_count, get_doc, get_group_by, get_list, new_doc
from ..export import XLSX, export_xlsx
from ..exceptions import AuthenticationRequired, ValidationError, VeloraError
from ..meta.registry import registry
from ..meta.spec import PERM_TYPES
from ..workspace import resolve_desk_path
from ..permissions import Session, check_permission, has_permission, shared_names, session_as


def _session(request: Request) -> Session:
    if not site_mod.current().developer_mode:
        raise AuthenticationRequired("Authentication is not configured (Security engine pending)")
    user = request.headers.get("x-velora-user")
    if not user:
        raise AuthenticationRequired("Send X-Velora-User (developer mode)")
    roles = frozenset(r.strip() for r in request.headers.get("x-velora-roles", "").split(",") if r.strip())
    return Session(user, roles)


def _json(value, name):
    if value is None:
        return None
    try:
        return json.loads(value)
    except ValueError:
        raise ValidationError(f"{name} must be valid JSON") from None


def create_app(auto_init: bool = True, frontend_dist: str | None = None, workspace=None, site: str | None = None, plane=None,
               use_platform: bool | None = None) -> FastAPI:
    """Modes:
      * single-site (workspace=None): velora.init(); developer-header auth
      * workspace sites: the site is chosen per request from the Host header; developer-header auth
      * platform: a control plane exists in the workspace -> real sign-in, company switching, per-company databases
    """
    from ..controlplane import ControlPlane
    if plane is None and workspace is not None and site is None and use_platform is not False and ControlPlane.exists(workspace):
        plane = ControlPlane.open(workspace)
    @asynccontextmanager
    async def lifespan(app):
        if auto_init and workspace is None:
            runtime.init()
        yield
        from ..realtime import HUB
        HUB.close()                                  # stop the live-event listener threads
        if plane is not None:
            plane.dispose()

    from .. import __version__ as _velora_version
    app = FastAPI(title="Velora", version=_velora_version, lifespan=lifespan)

    @app.exception_handler(VeloraError)
    async def velora_error(request, exc: VeloraError):
        return JSONResponse(status_code=exc.status_code,
                            content={"error": type(exc).__name__, "message": str(exc), "details": exc.details})

    @app.exception_handler(DataError)
    async def bad_value(request, exc: DataError):
        """A value the DATABASE refuses (a NUL byte, a number out of range, an over-long text) is the caller's mistake, not a server fault: 422, not 500. PostgreSQL is strict about
        these where SQLite is not, so the same hostile request used to be a clean answer on one and a crash on the other."""
        return JSONResponse(status_code=422, content={"error": "ValidationError", "message": "A value in the request is not acceptable (invalid characters or out of range)", "details": None})

    @app.exception_handler(OperationalError)
    @app.exception_handler(PoolTimeout)
    async def database_unavailable(request, exc):
        """No free database connection (pool exhausted or PostgreSQL out of slots): 503 with a retry hint, not a 500 traceback."""
        from .. import dbpool
        busy = isinstance(exc, PoolTimeout) or dbpool.is_connection_exhaustion(exc)
        return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                            content={"error": "DatabaseBusy" if busy else "DatabaseUnavailable",
                                     "message": "The database has no free connection right now; try again in a few seconds." if busy else "The database is unavailable.", "details": None})

    @contextmanager
    def legacy_scope(request: Request):
        with session_as(_session(request)):
            yield

    if plane is not None:
        from .platform import install_auth_routes, make_scope
        scope = make_scope(plane)
        install_auth_routes(app, plane)
    else:
        scope = legacy_scope

        @app.get("/api/auth/config")
        def auth_config():
            return {"data": {"mode": "developer"}}

    def run(request: Request, fn):
        with scope(request), db.transaction():
            return jsonable_encoder({"data": fn()})

    from .designer import install_designer_routes
    from .notifications import install_notification_routes
    from .extra import install_report_routes, install_theme_routes, install_financial_layout_routes, install_rule_routes
    install_theme_routes(app, scope, run, workspace)
    install_designer_routes(app, scope, run, workspace)
    from .application_builder import install_routes as install_application_builder_routes
    install_application_builder_routes(app, scope, run, workspace)
    from .app_extensions import install_routes as install_app_extension_routes
    install_app_extension_routes(app, scope, run, workspace)
    from .branding import install_routes as install_branding_routes
    install_branding_routes(app, scope, run)
    install_notification_routes(app, scope, run, workspace)
    from .search import install_search_routes
    install_search_routes(app, scope, run)
    from .dataimport import install_dataimport_routes
    install_dataimport_routes(app, scope, run)
    from .welcome import install_welcome_routes
    install_welcome_routes(app, scope, run, workspace, plane)
    install_report_routes(app, scope, run)
    from .hr import install_hr_routes
    install_hr_routes(app, run)
    from .hr_operations import install_hr_operations_routes
    install_hr_operations_routes(app, run)
    from .hr_governance import install_hr_governance_routes
    install_hr_governance_routes(app, run)
    install_financial_layout_routes(app, scope, run)
    install_rule_routes(app, scope, run)
    from .extra import install_policy_governance_routes
    install_policy_governance_routes(app, scope, run)
    from .extra import install_settings_governance_routes
    install_settings_governance_routes(app, scope, run)
    from .operational_centre import install_operational_centre_routes
    install_operational_centre_routes(app, run)
    from .finance_requests import install_finance_request_routes
    install_finance_request_routes(app, run)
    from ..workflows import install_routes as install_workflow_routes
    from ..workflow_automation import install_routes as install_workflow_automation_routes
    from ..dashboards import install_routes as install_dashboard_routes
    from ..printing import install_routes as install_print_routes
    from ..website import install_routes as install_website_routes
    install_workflow_routes(app, scope, run)
    from ..setup_copy import install_routes as install_setup_copy_routes
    install_setup_copy_routes(app, run)
    install_workflow_automation_routes(app, scope, run)
    install_dashboard_routes(app, scope, run)
    from ..application_workspaces import install_routes as install_workspace_routes
    install_workspace_routes(app, run)
    from ..activity import install_routes as install_activity_routes
    install_activity_routes(app, run)
    install_print_routes(app, scope, run)
    install_website_routes(app, scope, run, plane)
    from ..portal import install_routes as install_portal_routes
    install_portal_routes(app, scope, run, plane)
    from .document_actions import install_routes as install_document_action_routes
    install_document_action_routes(app, scope, run)
    from .app_routes import install_app_routes
    install_app_routes(app, scope, run)
    from ..files import install_routes as install_file_routes
    install_file_routes(app, scope, run)
    from .integrations import install_integration_routes
    install_integration_routes(app, scope, run)
    from ..ai import install_routes as install_ai_routes
    install_ai_routes(app, run)
    from ..ai_developer import install_routes as install_ai_developer_routes
    install_ai_developer_routes(app, run)
    from .jobs import install_job_routes
    install_job_routes(app, scope, run)
    from ..scripts import install_routes as install_script_routes
    install_script_routes(app, scope, run)
    from ..meta.extensions import install_routes as install_metadata_extension_routes
    install_metadata_extension_routes(app, scope, run)

    @app.get("/api/health")
    def health():
        from ..upgrade.versions import code_version
        return {"status": "ok", "version": code_version()}

    @app.get("/api/doctypes")
    def doctypes(request: Request):
        """Top-level DocTypes the caller can read - drives the sidebar."""
        def fn():
            return [{"name": d.name, "module": d.module, "app": d.app, "is_submittable": d.is_submittable,
                     "can_create": has_permission(d, "create")}
                    for d in sorted(registry.all(), key=lambda d: (d.module, d.name))
                    if not d.istable and not d.hide_from_menu and (has_permission(d, "read") or shared_names(d.name, "read") or shared_names(d.name, "write"))]
        return run(request, fn)

    @app.get("/api/meta/{doctype}")
    def meta(doctype: str, request: Request):
        def fn():
            m = registry.get(doctype)
            if not m.istable:   # child tables inherit access from their parent document
                if not has_permission(m, "read") and not shared_names(doctype, "read") and not shared_names(doctype, "write"):
                    check_permission(m, "read")
            d = m.to_dict()
            d["permissions"] = {p: has_permission(m, p) for p in PERM_TYPES} if not m.istable else {}
            from .designer import apply_customizations
            return apply_customizations(m, d)
        return run(request, fn)

    @app.get("/api/count/{doctype}")
    def count(doctype: str, request: Request, filters: str | None = None):
        return run(request, lambda: get_count(doctype, _json(filters, "filters")))

    @app.get("/api/aggregate/{doctype}")
    def aggregate(doctype: str, request: Request, fields: str, filters: str | None = None):
        return run(request, lambda: get_aggregate(doctype, _json(fields, "fields") or [], _json(filters, "filters")))

    @app.get("/api/group_by/{doctype}")
    def group_by(doctype: str, request: Request, field: str, filters: str | None = None):
        return run(request, lambda: get_group_by(doctype, field, _json(filters, "filters")))

    @app.post("/api/export/{doctype}")
    def export(doctype: str, request: Request, body: dict = Body(default={})):
        """Excel export. body: {filters, columns, all_fields, names, order_by, header}"""
        with scope(request), db.transaction():
            data, filename, rows = export_xlsx(
                doctype, filters=body.get("filters"), columns=body.get("columns"), all_fields=bool(body.get("all_fields")),
                names=body.get("names"), order_by=body.get("order_by"), header=body.get("header", "label"))
        return Response(data, media_type=XLSX, headers={
            "Content-Disposition": f'attachment; filename="{filename}"', "X-Velora-Rows": str(rows),
            "Access-Control-Expose-Headers": "Content-Disposition, X-Velora-Rows"})

    @app.post("/api/bulk/{doctype}")
    def bulk(doctype: str, request: Request, body: dict = Body(...)):
        with scope(request):   # no outer transaction: bulk_action commits per document
            results = bulk_action(doctype, body.get("action", ""), body.get("names") or [], body.get("values"))
        return jsonable_encoder({"data": results})

    @app.get("/api/client_script/{doctype}")
    def client_script(doctype: str, request: Request, kind: str = "form"):
        """JS shipped with the app next to the DocType (<name>.js / <name>_list.js). Trusted app code."""
        with scope(request):
            m = registry.get(doctype)
            if not m.istable:
                check_permission(m, "read")
            stem = Path(m.source).stem if m.source else ""
            fname = f"{stem}_list.js" if kind == "list" else f"{stem}.js"
            path = m.directory / fname if m.directory else None
            text = path.read_text() if path and path.is_file() else ""
            from ..scripts import client_code
            company_code = client_code(doctype, kind)
            text = "\n;\n".join(x for x in (text, company_code) if x)
        return PlainTextResponse(text, media_type="application/javascript")

    @app.get("/api/resource/{doctype}")
    def list_docs(doctype: str, request: Request, filters: str | None = None, fields: str | None = None,
                  order_by: str | None = None, limit: int = Query(20), offset: int = 0):
        return run(request, lambda: get_list(doctype, _json(filters, "filters"), _json(fields, "fields"),
                                             order_by, limit, offset))

    @app.post("/api/resource/{doctype}", status_code=201)
    def create(doctype: str, request: Request, body: dict = Body(...)):
        def fn():
            values = dict(body)
            if registry.get(doctype).autoname != "prompt":
                values.pop("name", None)   # clients cannot choose names unless the DocType says so
            for k in ("owner", "creation", "modified", "modified_by", "docstatus", "doctype"):    # "doctype" comes from the URL, never the body (it used to collide: TypeError, 500)
                values.pop(k, None)
            return new_doc(doctype, **values).insert().as_dict()
        return run(request, fn)

    @app.get("/api/resource/{doctype}/{name}/copy")
    def copy_doc(doctype: str, name: str, request: Request, mode: str = "duplicate"):
        """Values for a new, unsaved form copied from this document: mode=amend (a cancelled document, once) or mode=duplicate."""
        from ..document import amend
        return run(request, lambda: amend.copy_values(doctype, name, mode))

    @app.get("/api/resource/{doctype}/{name}/correction-options")
    def correction_options(doctype: str, name: str, request: Request):
        from ..document.correction import correction_options as get_options
        return run(request, lambda: get_options(doctype, name))

    @app.get("/api/resource/{doctype}/{name}/amended-to")
    def amended_to(doctype: str, name: str, request: Request):
        from ..document import amend

        def fn():
            get_doc(doctype, name)                                          # you must be able to read it
            return {"amended_to": amend.amendment_of(doctype, name)}
        return run(request, fn)

    @app.get("/api/resource/{doctype}/{name}")
    def read(doctype: str, name: str, request: Request):
        return run(request, lambda: get_doc(doctype, name).as_dict())

    @app.put("/api/resource/{doctype}/{name}")
    def update(doctype: str, name: str, request: Request, body: dict = Body(...)):
        def fn():
            doc = get_doc(doctype, name)
            values = {k: v for k, v in body.items() if k not in ("name", "owner", "creation", "modified_by", "docstatus")}
            doc.update(values)   # a client-supplied `modified` is what the optimistic lock compares
            return doc.save().as_dict()
        return run(request, fn)

    @app.delete("/api/resource/{doctype}/{name}")
    def remove(doctype: str, name: str, request: Request, body: dict = Body(default={} )):
        def fn():
            get_doc(doctype, name).delete(reason=body.get("reason"))
            return {"deleted": name}
        return run(request, fn)

    @app.post("/api/resource/{doctype}/{name}/{action}")
    def transition(doctype: str, name: str, action: str, request: Request, body: dict = Body(default={} )):
        def fn():
            if action not in ("submit", "cancel"):
                raise ValidationError(f"Unknown action {action!r}")
            doc = get_doc(doctype, name)
            if action == "cancel": doc.cancel(reason=body.get("reason"))
            else: doc.submit()
            return doc.as_dict()
        return run(request, fn)

    from ..document.recycle_bin import install_routes as install_deleted_inbox
    install_deleted_inbox(app, run)

    dist = frontend_dist or resolve_desk_path(workspace)
    if dist and os.path.isdir(dist):
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")   # after API routes
    if workspace is not None and plane is None:
        from .sites import SiteMiddleware, SiteResolver
        app.add_middleware(SiteMiddleware, resolver=SiteResolver(workspace, forced=site))
    if workspace is not None:
        from ..upgrade.maintenance import MaintenanceMiddleware
        from ..upgrade.state import gate_message

        def platform_gate():
            st, rec = plane.pending_upgrade()
            return None if st == "ok" else ("UpgradePending", gate_message(st, rec))
        app.add_middleware(MaintenanceMiddleware, ws=workspace, blockers=[platform_gate] if plane is not None else [])
    from .limits import BodyLimitMiddleware
    app.add_middleware(BodyLimitMiddleware)                                  # outermost of all: an oversized body is refused before anything else sees it
    return app
