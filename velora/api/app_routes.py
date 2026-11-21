"""Let installed applications contribute their own API routes.

An app declares in hooks.py:

    api_routes_provider = "myapp.api.routes"

(or registers the module under the ``velora.api_routes`` entry-point group, which works before any site exists)
and that module defines ``install_routes(app, scope, run)``. ``run(request, fn)`` executes ``fn`` inside the
request's site scope and database transaction and wraps the result as ``{"data": ...}``, exactly like the
framework's own routes, so permissions, errors and auditing behave the same.
"""
from __future__ import annotations

import importlib

from ..exceptions import ValidationError
from ..meta.registry import registry


def _hook_modules() -> list[str]:
    """Providers declared in the hooks of the apps installed on the current site (none when no site is selected yet)."""
    try:
        apps = list(registry.apps)
    except RuntimeError:                       # the API is being built before any site is selected
        return []
    out = []
    for app_name in apps:
        try:
            hooks = importlib.import_module(f"{app_name}.hooks")
        except ModuleNotFoundError as exc:
            if exc.name == f"{app_name}.hooks":
                continue
            raise
        path = getattr(hooks, "api_routes_provider", None)
        if not path:
            continue
        if not isinstance(path, str) or "." not in path:
            raise ValidationError(f"{app_name}.hooks.api_routes_provider must be a dotted module path")
        out.append(path)
    return out


def _entry_point_modules() -> list[str]:
    from importlib.metadata import entry_points
    return [ep.value for ep in entry_points(group="velora.api_routes")]


def install_app_routes(app, scope, run):
    """Routes are installed once per process; each handler checks the current site's own metadata, so a site without the app is refused cleanly."""
    for path in dict.fromkeys(_hook_modules() + _entry_point_modules()):
        module = importlib.import_module(path)
        install = getattr(module, "install_routes", None)
        if not callable(install):
            raise ValidationError(f"{path} must define install_routes(app, scope, run)")
        install(app, scope, run)
