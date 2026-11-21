"""Company-scoped installed application extension discovery and asset delivery."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

from ..app_runtime import resolve_declared_asset
from ..exceptions import ValidationError
from ..workspace import WorkspaceError


def install_routes(app: FastAPI, scope, run, workspace=None):
    @app.get("/api/app-extensions")
    def app_extensions(request: Request):
        def fn():
            from ..meta.registry import registry
            return registry.app_extensions()
        return run(request, fn)

    @app.get("/api/marketplace")
    def marketplace_catalogue(request: Request):
        def fn():
            if workspace is None:
                return []
            from ..marketplace import list_packages
            return list_packages(workspace)
        return run(request, fn)

    @app.get("/api/app-assets/{app_name}/{asset_path:path}")
    def app_asset(app_name: str, asset_path: str, request: Request):
        with scope(request):
            try:
                path, media_type = resolve_declared_asset(app_name, asset_path)
            except WorkspaceError as exc:
                raise ValidationError(str(exc)) from None
            return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/company/setup-readiness")
    def company_setup_readiness(request: Request):
        """Company-scoped setup checklist supplied by the installed ERP application."""
        def fn():
            import importlib
            from ..meta.registry import registry
            providers = []
            for app_name in registry.apps:
                try:
                    hooks = importlib.import_module(f"{app_name}.hooks")
                except ModuleNotFoundError as exc:
                    if exc.name == f"{app_name}.hooks":
                        continue
                    raise
                path = getattr(hooks, "setup_readiness_provider", None)
                if path:
                    if not isinstance(path, str) or "." not in path:
                        raise ValidationError(f"{app_name}.hooks.setup_readiness_provider must be a dotted module path")
                    providers.append((app_name, importlib.import_module(path)))
            if len(providers) > 1:
                raise ValidationError("Only one installed application may provide company setup readiness.")
            if not providers:
                return {"status": "not_available", "checks": []}
            provider = providers[0][1]
            return provider.setup_readiness()
        return run(request, fn)
