"""Safe application scaffolding endpoints for Developer Studio.

The builder creates source files only inside the configured workspace apps directory.
It never installs or executes newly-created application code automatically.
"""
from __future__ import annotations

from fastapi import Body, FastAPI, Request
from fastapi.responses import StreamingResponse
from io import BytesIO

from .. import site as site_mod
from ..exceptions import PermissionDenied, ValidationError
from ..permissions import get_session
from ..scaffold import new_app
from ..app_package import build_app_archive, inspect_app
from ..workspace import Workspace, WorkspaceError
from .. import apps as app_manager


def _require_developer(workspace):
    session = get_session()
    if session.user != "Administrator" and "System Manager" not in session.roles:
        raise PermissionDenied("Only a System Manager can create applications")
    if not site_mod.current().developer_mode and not (workspace and workspace.common_config().get("developer_mode")):
        raise PermissionDenied("Application Builder requires developer mode")


def install_routes(app: FastAPI, scope, run, workspace=None):
    @app.post("/api/devtools/apps")
    def create_application(request: Request, body: dict = Body(...)):
        def fn():
            ws = workspace or Workspace.discover()
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Application Builder requires a Velora workspace")
            name = body.get("name")
            module = body.get("module") or None
            title = body.get("title") or None
            try:
                path = new_app(ws.apps_dir, name, module=module, title=title)
            except (WorkspaceError, ValueError, TypeError) as exc:
                raise ValidationError(str(exc)) from None
            return {
                "name": name,
                "module": module or name.replace("_", " ").title(),
                "path": str(path),
                "created": True,
                "next_steps": [
                    "Review the generated hooks.py and README.md",
                    "Add DocTypes and controllers to the application package",
                    "Register the app in the workspace and install it on the intended site",
                ],
                "installed": False,
            }
        return run(request, fn)
    @app.get("/api/devtools/apps/{name}/validate")
    def validate_application(name: str, request: Request):
        def fn():
            ws = workspace or Workspace.discover()
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Application Builder requires a Velora workspace")
            return inspect_app(ws, name)
        return run(request, fn)

    @app.get("/api/devtools/apps/{name}/package")
    def package_application(name: str, request: Request):
        ws = workspace or Workspace.discover()
        with scope(request):
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Application Builder requires a Velora workspace")
            try:
                data, report = build_app_archive(ws, name)
            except (WorkspaceError, ValueError, TypeError) as exc:
                raise ValidationError(str(exc)) from None
        filename = f"{name}-{report['version']}.zip"
        return StreamingResponse(BytesIO(data), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"'})


    @app.get("/api/devtools/lifecycle")
    def lifecycle_catalog(request: Request):
        def fn():
            ws = workspace or Workspace.discover()
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Application Lifecycle Manager requires a Velora workspace")
            ws.activate()
            site = site_mod.current()
            installed = set(site.installed_apps())
            available = list(dict.fromkeys([*ws.apps(), *app_manager.BUNDLED_APPS]))
            rows = []
            for name in available:
                hooks = app_manager._hooks(name)
                rows.append({"name": name, "version": app_manager.app_version(name), "installed": name in installed,
                             "required_apps": list(getattr(hooks, "required_apps", []) or []),
                             "required_velora": str(getattr(hooks, "required_velora", "") or ""),
                             "path": str(ws.app_path(name)) if name in ws.apps() else "bundled"})
            return {"site": site.name, "apps": rows}
        return run(request, fn)

    @app.post("/api/devtools/lifecycle/{name}/install")
    def lifecycle_install(name: str, request: Request):
        def fn():
            ws = workspace or Workspace.discover()
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Application Lifecycle Manager requires a Velora workspace")
            ws.activate()
            try:
                plan = app_manager.install_app(ws, site_mod.current(), name)
            except (WorkspaceError, ValueError, TypeError) as exc:
                raise ValidationError(str(exc)) from None
            return {"installed": name, "site": site_mod.current().name, "migration_plan": plan,
                    "data_policy": "Existing records are retained; installation does not purge application data."}
        return run(request, fn)

    @app.post("/api/devtools/lifecycle/{name}/uninstall")
    def lifecycle_uninstall(name: str, request: Request):
        def fn():
            ws = workspace or Workspace.discover()
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Application Lifecycle Manager requires a Velora workspace")
            ws.activate()
            try:
                app_manager.uninstall_app(ws, site_mod.current(), name)
            except (WorkspaceError, ValueError, TypeError) as exc:
                raise ValidationError(str(exc)) from None
            return {"uninstalled": name, "site": site_mod.current().name,
                    "data_policy": "Application tables and records are retained. Uninstall does not delete company data."}
        return run(request, fn)


    # Deployment Centre: profiles are stored in the control workspace; promotion
    # is explicit and always offers a non-mutating plan before a live release.
    @app.get("/api/devtools/deploy/profiles")
    def deployment_profiles(request: Request):
        def fn():
            ws = workspace or Workspace.discover()
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Deployment Centre requires a Velora workspace")
            from ..deployment import list_profiles
            return list_profiles(ws)
        return run(request, fn)

    @app.post("/api/devtools/deploy/profiles")
    def deployment_profile_create(request: Request, body: dict = Body(...)):
        def fn():
            ws = workspace or Workspace.discover()
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Deployment Centre requires a Velora workspace")
            from ..deployment import create_profile
            try:
                return create_profile(ws, str(body.get("name") or ""), str(body.get("source") or ""),
                                      str(body.get("target") or ""), list(body.get("apps") or []))
            except (WorkspaceError, ValueError, TypeError, KeyError) as exc:
                raise ValidationError(str(exc)) from None
        return run(request, fn)

    @app.get("/api/devtools/deploy/profiles/{name}/plan")
    def deployment_profile_plan(name: str, request: Request):
        def fn():
            ws = workspace or Workspace.discover()
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Deployment Centre requires a Velora workspace")
            from ..deployment import build_plan
            try:
                return build_plan(ws, name)
            except (WorkspaceError, ValueError, TypeError, KeyError) as exc:
                raise ValidationError(str(exc)) from None
        return run(request, fn)

    @app.post("/api/devtools/deploy/profiles/{name}/promote")
    def deployment_profile_promote(name: str, request: Request, body: dict = Body(...)):
        def fn():
            ws = workspace or Workspace.discover()
            _require_developer(ws)
            if ws is None:
                raise ValidationError("Deployment Centre requires a Velora workspace")
            dry_run = bool(body.get("dry_run", True))
            if not dry_run and body.get("confirm") is not True:
                raise ValidationError("Live deployment requires explicit confirmation")
            from ..deployment import promote
            try:
                return promote(ws, name, dry_run=dry_run)
            except (WorkspaceError, ValueError, TypeError, KeyError) as exc:
                raise ValidationError(str(exc)) from None
        return run(request, fn)
