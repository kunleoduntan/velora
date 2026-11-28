"""Apps can contribute API routes without a site being selected while the API is built."""
import sys, types
from fastapi import FastAPI
from velora.api import app_routes


def test_entry_point_and_hook_modules_are_installed_once(monkeypatch):
    calls = []
    mod = types.ModuleType("fake_routes_mod"); mod.install_routes = lambda app, scope, run: calls.append(scope)
    monkeypatch.setitem(sys.modules, "fake_routes_mod", mod)
    monkeypatch.setattr(app_routes, "_hook_modules", lambda: ["fake_routes_mod"])
    monkeypatch.setattr(app_routes, "_entry_point_modules", lambda: ["fake_routes_mod"])
    app_routes.install_app_routes(FastAPI(), "scope", lambda r, f: f())
    assert calls == ["scope"], "the same provider declared twice is installed once"


def test_no_site_means_no_hook_modules_and_not_an_error():
    assert isinstance(app_routes._hook_modules(), list)
