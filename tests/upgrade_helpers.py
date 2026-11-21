"""Shared fixtures for the upgrade tests: a real workspace with a control plane, an app, and companies."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import velora
from velora import site as site_mod
from velora.controlplane import ControlPlane
from velora.scaffold import new_app, new_doctype
from velora.settings import set_setting
from velora.workspace import Workspace

PW = "correct horse battery"
OLD = "0.7.0"


def clean_modules(tmp_path, before_path, before_mods):
    site_mod.unload_all()
    velora.shutdown()
    sys.path[:] = before_path
    for name in set(sys.modules) - before_mods:
        f = getattr(sys.modules[name], "__file__", None) or ""
        if str(tmp_path) in f or str(tmp_path) in str(getattr(sys.modules[name], "__path__", "")):
            del sys.modules[name]


def make_app(ws, name="shop", doctype="Product", module="Retail"):
    root = new_app(ws.apps_dir, name, module=module)
    ws.register_app(name)
    d = new_doctype(root, name, doctype, module=module)
    p = d / f"{d.name}.json"
    spec = json.loads(p.read_text())
    spec["fields"].append({"fieldname": "price", "fieldtype": "Currency"})
    p.write_text(json.dumps(spec, indent=2))
    return root


def fresh_process(app="shop", root: Path | None = None):
    """A real upgrade runs in a NEW process that imports the new release; emulate that by dropping the cached modules
    AND the bytecode cache (Python trusts a .pyc when source mtime-in-seconds and size match - true for a same-second edit)."""
    import importlib
    import shutil
    for d in (root.rglob("__pycache__") if root else []):
        shutil.rmtree(d, ignore_errors=True)
    for m in [m for m in sys.modules if m == app or m.startswith(app + ".")]:
        del sys.modules[m]
    importlib.invalidate_caches()


def change_app(ws, app="shop", version="0.0.2", field=None, patch=None, doctype_folder="product", module_dir="retail", length=None, field_type=None):
    """Simulate shipping a new app release: version bump, a new field and/or a data patch."""
    root = ws.app_path(app) / app
    (root / "__init__.py").write_text(f'__version__ = "{version}"\n')
    if field or length or field_type:
        p = root / module_dir / "doctype" / doctype_folder / f"{doctype_folder}.json"
        spec = json.loads(p.read_text())
        if field:
            spec["fields"].append(field)
        for f in spec["fields"]:
            if length and f["fieldname"] == "title":
                f["length"] = length
            if field_type and f["fieldname"] == "title":
                f["fieldtype"] = field_type
        p.write_text(json.dumps(spec, indent=2))
    if patch:
        name, body = patch
        pdir = root / "patches"
        pdir.mkdir(exist_ok=True)
        (pdir / "__init__.py").write_text("")
        (pdir / f"{name}.py").write_text(body)
        txt = root / "patches.txt"
        txt.write_text(txt.read_text().rstrip() + f"\n{app}.patches.{name}\n")
    fresh_process(app, ws.app_path(app))


OK_PATCH = '''import velora
def execute():
    for d in velora.get_list("Product", fields=["name"], limit=100):
        doc = velora.get_doc("Product", d["name"])
        doc.title = (doc.title or "") + " [patched]"
        doc.save(ignore_permissions=True)
'''
FAIL_ON_B_PATCH = '''import velora
def execute():
    for d in velora.get_list("Product", fields=["name"], limit=100):
        doc = velora.get_doc("Product", d["name"])
        doc.title = (doc.title or "") + " [patched]"
        doc.save(ignore_permissions=True)
    if velora.current_company() and velora.current_company().id == "COMP-002":
        raise RuntimeError("boom in COMP-002")
'''
