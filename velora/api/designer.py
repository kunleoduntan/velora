"""Form-layout, grid-column and developer-tool endpoints.

  GET    /api/layout/{doctype}            the layout the form uses, plus the fields not yet placed
  PUT    /api/layout/{doctype}            {layout, target: "company"|"app"}  (System Manager; "app" needs developer mode and edits the app's JSON)
  DELETE /api/layout/{doctype}            remove this company's layout (back to the app's)
  GET/PUT/DELETE /api/grid/{doctype}      the same for a child table's grid columns
  GET    /api/devtools/status             is the DocType Creator available to me?
  POST   /api/devtools/doctype-creator/preview | create
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from ..workspace import Workspace

from fastapi import Body, FastAPI, Request

from .. import db, site as site_mod
from ..db import schema
from ..devtools import creator
from ..exceptions import MetaError, PermissionDenied, ValidationError
from ..meta import layout as lay
from ..meta.registry import registry
from ..permissions import check_permission, get_session
from ..settings import get_setting, set_setting

LAYOUT_KEY, GRID_KEY = "customize.layout.", "customize.grid."
FORM_APPEARANCE_KEY = "customize.form_appearance."


def is_manager() -> bool:
    s = get_session()
    return s.user == "Administrator" or "System Manager" in s.roles


def require_manager():
    if not is_manager():
        raise PermissionDenied("Only a System Manager can customise forms")


def developer_mode(workspace=None) -> bool:
    if site_mod.current().developer_mode:
        return True
    return bool(workspace is not None and workspace.common_config().get("developer_mode"))


def apply_customizations(meta, d: dict) -> dict:
    """Add the effective layout / grid columns (company override > app definition) to a /api/meta response."""
    d["can_customize"] = is_manager()
    if not meta.istable:
        d["form_appearance"] = get_setting(FORM_APPEARANCE_KEY + meta.name, {}) or {}
    if meta.istable:
        override = get_setting(GRID_KEY + meta.name)
        cols = override or meta.grid_columns
        if cols:
            d["grid_columns"] = cols
        return d
    override = get_setting(LAYOUT_KEY + meta.name)
    base = override or meta.layout
    if base:
        d["layout"] = lay.effective_layout(base, meta)
        d["layout_source"] = "company" if override else "app"
    return d


def _field_dicts(fields) -> list[dict]:
    return [f.to_dict() for f in fields]


class AppFolderReadOnly(Exception):
    pass


def _write_app_json(meta, key: str, value):
    """Developer mode: write the layout into the DocType's own JSON file (the file under version control)."""
    path = Path(meta.source)
    if not path.is_file() or path.suffix != ".json":
        raise MetaError(f"{meta.name} has no JSON file to write to")
    try:
        data = json.loads(path.read_text())
        data[key] = value
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)                                                # atomic: a crash never leaves half a file
    except OSError as exc:                                                    # an app installed from a wheel lives in a folder the service may not write to
        raise AppFolderReadOnly(f"The {meta.name} app files cannot be written by the Velora service ({exc.strerror or exc}). "
                                "The app is probably installed from a package (wheel), so its folder is read-only.") from exc


def install_designer_routes(app: FastAPI, scope, run, workspace=None):
    # ---------------- form layouts ----------------
    @app.get("/api/layout/{doctype}")
    def get_layout(doctype: str, request: Request):
        def fn():
            m = registry.get(doctype)
            if m.istable:
                raise ValidationError(f"{doctype} is a child table: use /api/grid/{doctype}")
            check_permission(m, "read")
            override = get_setting(LAYOUT_KEY + doctype)
            base = override or m.layout
            source = "company" if override else "app" if m.layout else "auto"
            layout = base or lay.derive_layout(m)
            return {"source": source, "layout": layout, "appearance": get_setting(FORM_APPEARANCE_KEY + doctype, {}) or {},
                    "unplaced": _field_dicts(lay.unplaced_fields(layout, m)),
                    "fields": _field_dicts(f for f in m.fields if not f.is_layout), "editable": is_manager(), "can_write_app": is_manager() and developer_mode(workspace)}
        return run(request, fn)

    @app.put("/api/layout/{doctype}")
    def put_layout(doctype: str, request: Request, body: dict = Body(...)):
        def fn():
            require_manager()
            m = registry.get(doctype)
            if m.istable:
                raise ValidationError(f"{doctype} is a child table: use /api/grid/{doctype}")
            errs = lay.validate_layout(body.get("layout"), m)
            if errs:
                raise ValidationError("The layout is not valid:\n- " + "\n- ".join(errs[:20]))
            clean = lay.normalize_layout(body["layout"])
            target = body.get("target", "company")
            if target == "app":
                if not developer_mode(workspace):
                    raise PermissionDenied("Writing into the app needs developer mode")
                try:
                    _write_app_json(m, "layout", clean)
                except AppFolderReadOnly as exc:                              # never a 500: keep the work as this company's layout and say so
                    set_setting(LAYOUT_KEY + doctype, clean)
                    return {"saved": "company", "layout": clean, "note": f"{exc} Your layout was saved for this company instead."}
                site_mod.current().load()
                set_setting(LAYOUT_KEY + doctype, None)                       # the app's layout now applies; a stale company copy would hide it
            elif target == "company":
                set_setting(LAYOUT_KEY + doctype, clean)
            else:
                raise ValidationError("target must be 'company' or 'app'")
            return {"saved": target, "layout": clean}
        return run(request, fn)

    @app.delete("/api/layout/{doctype}")
    def reset_layout(doctype: str, request: Request):
        def fn():
            require_manager()
            registry.get(doctype)
            set_setting(LAYOUT_KEY + doctype, None)
            return {"reset": doctype}
        return run(request, fn)

    # ---------------- field-level form appearance (separate from DocType schema/layout) ----------------
    ALLOWED_LABEL_POSITIONS = {"top", "left"}
    ALLOWED_CONTROL_SIZES = {"small", "medium", "large"}
    ALLOWED_DISPLAY_STYLES = {"standard", "compact", "emphasized"}

    def _clean_form_appearance(raw, meta):
        if not isinstance(raw, dict):
            raise ValidationError("form appearance must be an object keyed by fieldname")
        fields = {f.fieldname: f for f in meta.fields if not f.is_layout}
        if len(raw) > 500:
            raise ValidationError("form appearance contains too many field definitions")
        cleaned = {}
        for fieldname, cfg in raw.items():
            if fieldname not in fields or not isinstance(cfg, dict):
                raise ValidationError(f"Unknown field or invalid appearance definition: {fieldname}")
            if set(cfg) - {"label_position", "control_size", "display_style", "placeholder", "help_text", "show_description", "readonly_style"}:
                raise ValidationError(f"Unsupported appearance property for {fieldname}")
            out = {}
            if "label_position" in cfg:
                if cfg["label_position"] not in ALLOWED_LABEL_POSITIONS: raise ValidationError(f"{fieldname}: invalid label_position")
                out["label_position"] = cfg["label_position"]
            if "control_size" in cfg:
                if cfg["control_size"] not in ALLOWED_CONTROL_SIZES: raise ValidationError(f"{fieldname}: invalid control_size")
                out["control_size"] = cfg["control_size"]
            if "display_style" in cfg:
                if cfg["display_style"] not in ALLOWED_DISPLAY_STYLES: raise ValidationError(f"{fieldname}: invalid display_style")
                out["display_style"] = cfg["display_style"]
            for key in ("placeholder", "help_text"):
                if key in cfg:
                    if not isinstance(cfg[key], str) or len(cfg[key]) > 500:
                        raise ValidationError(f"{fieldname}: {key} must be text of at most 500 characters")
                    if cfg[key]: out[key] = cfg[key]
            for key in ("show_description", "readonly_style"):
                if key in cfg:
                    if not isinstance(cfg[key], bool): raise ValidationError(f"{fieldname}: {key} must be boolean")
                    out[key] = cfg[key]
            if out: cleaned[fieldname] = out
        return cleaned

    @app.get("/api/form-appearance/{doctype}")
    def get_form_appearance(doctype: str, request: Request):
        def fn():
            m = registry.get(doctype)
            if m.istable: raise ValidationError("Child tables use grid presentation settings")
            check_permission(m, "read")
            return {"appearance": get_setting(FORM_APPEARANCE_KEY + doctype, {}) or {}, "fields": _field_dicts(f for f in m.fields if not f.is_layout),
                    "editable": is_manager()}
        return run(request, fn)

    @app.put("/api/form-appearance/{doctype}")
    def put_form_appearance(doctype: str, request: Request, body: dict = Body(...)):
        def fn():
            require_manager()
            m = registry.get(doctype)
            if m.istable: raise ValidationError("Child tables use grid presentation settings")
            clean = _clean_form_appearance(body.get("appearance"), m)
            set_setting(FORM_APPEARANCE_KEY + doctype, clean)
            return {"appearance": clean}
        return run(request, fn)

    @app.delete("/api/form-appearance/{doctype}")
    def reset_form_appearance(doctype: str, request: Request):
        def fn():
            require_manager()
            m = registry.get(doctype)
            set_setting(FORM_APPEARANCE_KEY + doctype, None)
            return {"reset": doctype}
        return run(request, fn)

    # ---------------- grid columns (child tables) ----------------
    @app.get("/api/grid/{doctype}")
    def get_grid(doctype: str, request: Request):
        def fn():
            m = registry.get(doctype)
            if not m.istable:
                raise ValidationError(f"{doctype} is not a child table")
            override = get_setting(GRID_KEY + doctype)
            cols = override or m.grid_columns
            return {"source": "company" if override else "app" if m.grid_columns else "auto", "columns": cols or [],
                    "fields": _field_dicts(f for f in m.fields if not f.is_layout and f.fieldtype != "Table"), "editable": is_manager()}
        return run(request, fn)

    @app.put("/api/grid/{doctype}")
    def put_grid(doctype: str, request: Request, body: dict = Body(...)):
        def fn():
            require_manager()
            m = registry.get(doctype)
            if not m.istable:
                raise ValidationError(f"{doctype} is not a child table")
            errs = lay.validate_grid_columns(body.get("columns"), m)
            if errs:
                raise ValidationError("The grid columns are not valid:\n- " + "\n- ".join(errs[:20]))
            clean = lay.normalize_grid_columns(body["columns"])
            if body.get("target", "company") == "app":
                if not developer_mode(workspace):
                    raise PermissionDenied("Writing into the app needs developer mode")
                try:
                    _write_app_json(m, "grid_columns", clean)
                except AppFolderReadOnly as exc:
                    set_setting(GRID_KEY + doctype, clean)
                    return {"columns": clean, "saved": "company", "note": f"{exc} Your columns were saved for this company instead."}
                site_mod.current().load()
                set_setting(GRID_KEY + doctype, None)
            else:
                set_setting(GRID_KEY + doctype, clean)
            return {"columns": clean}
        return run(request, fn)

    @app.delete("/api/grid/{doctype}")
    def reset_grid(doctype: str, request: Request):
        def fn():
            require_manager()
            registry.get(doctype)
            set_setting(GRID_KEY + doctype, None)
            return {"reset": doctype}
        return run(request, fn)

    # ---------------- developer tools ----------------
    @app.get("/api/devtools/status")
    def devtools_status(request: Request):
        def fn():
            ok = is_manager() and developer_mode(workspace)
            return {"available": ok, "apps": list(registry.apps) if ok else []}
        return run(request, fn)

    @app.get("/api/devtools/catalog")
    def devtools_catalog(request: Request):
        def fn():
            require_manager()
            if not developer_mode(workspace):
                raise PermissionDenied("Developer Studio requires developer mode")
            from ..devtools.studio import catalog
            return catalog()
        return run(request, fn)

    @app.get("/api/devtools/doctype/{doctype}")
    def devtools_inspect_doctype(doctype: str, request: Request):
        def fn():
            require_manager()
            if not developer_mode(workspace):
                raise PermissionDenied("Developer Studio requires developer mode")
            from ..devtools.studio import inspect_doctype
            return inspect_doctype(doctype)
        return run(request, fn)

    def _creator_args(body: dict):
        require_manager()
        if not developer_mode(workspace):
            raise PermissionDenied("The DocType Creator writes files into an app, so it needs developer mode")
        raw = body.get("json")
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError as e:
            raise ValidationError(f"The JSON is not valid: {e}") from None
        if not isinstance(body.get("app"), str) or not body["app"]:
            raise ValidationError("Choose the app to create the DocTypes in")
        flags = {k: body.get(k) for k in ("is_child", "is_submittable", "track_changes", "is_autoname", "autoname_field_name") if body.get(k) is not None}
        return data, dict(app=body["app"], module=body.get("module") or None, name=body.get("name") or None, flags=flags, on_conflict=body.get("on_conflict") or "error")

    @app.post("/api/devtools/doctype-creator/preview")
    def creator_preview(request: Request, body: dict = Body(...)):
        def fn():
            data, kw = _creator_args(body)
            return creator.plan(data, **kw).report()
        return run(request, fn)

    @app.post("/api/devtools/doctype-creator/create")
    def creator_create(request: Request, body: dict = Body(...)):
        def fn():
            data, kw = _creator_args(body)
            p = creator.plan(data, **kw)
            try:
                out = creator.create(p)                                        # raises (and writes nothing) if anything is wrong
            except MetaError as e:
                raise ValidationError(str(e)) from None
            site = site_mod.current()
            site.load()                                                        # pick up the new files ...
            with db.transaction():
                out["migration"] = schema.migrate()                           # ... and create their tables in THIS database
            out["note"] = "Other companies/sites pick the new tables up with `velora upgrade`."
            ws = workspace or Workspace.discover()
            folders = []
            for f in out.get("files", []):                                     # where each DocType's files are, as the File Explorer names them
                try:
                    rel = Path(f).parent.relative_to(ws.apps_dir)
                    folder = "apps/" + rel.as_posix()
                    if folder not in folders:
                        folders.append(folder)
                except (ValueError, AttributeError):
                    pass
            out["folders"] = folders
            return out
        return run(request, fn)

    # ---------------- company-local DocType object manager ----------------
    COMPANY_DOCTYPES_KEY = "meta.company_doctypes"
    COMPANY_DOCTYPES_ARCHIVE_KEY = "meta.company_doctypes_archive"

    def _company_doctypes():
        return get_setting(COMPANY_DOCTYPES_KEY, []) or []

    def _activate_company_doctypes(definitions):
        site = site_mod.current()
        site.registry.load_company_doctypes(definitions)
        site.reset_tables()

    def _refuse_shared_table(name: str, archived=None):
        """A company object must have a table of its own: refuse a name that maps to the same table as another DocType (including archived ones, which still own their data)."""
        archived_names = tuple((x.get("definition") or {}).get("name", "") for x in (get_setting(COMPANY_DOCTYPES_ARCHIVE_KEY, []) or []))
        other = registry.table_collision(name, ignore=tuple(archived or ()), extra_names=archived_names)
        if other:
            raise ValidationError(f"{name!r} would share its database table with {other!r}. Use a name that is different once punctuation and spaces are ignored.")

    def _normalise_company_doctype(spec: dict, name: str | None = None):
        if not isinstance(spec, dict):
            raise ValidationError("DocType definition must be a JSON object")
        raw = dict(spec)
        if name:
            raw["name"] = name
        raw.setdefault("module", "Custom")
        try:
            meta = __import__("velora.meta.spec", fromlist=["DocType"]).DocType.from_dict(raw, app="company", source=f"company://{raw.get('name', '')}")
        except MetaError as exc:
            raise ValidationError(str(exc)) from None
        return meta.to_dict()

    @app.get("/api/devtools/objects")
    def company_objects_list(request: Request):
        def fn():
            require_manager()
            site = site_mod.current()
            return {"company": (site.company or {}).get("company_name") or (site.company or {}).get("name") or site.name,
                    "objects": [{"name": d.name, "module": d.module, "app": d.app, "field_count": len(d.fields), "is_child": d.istable,
                                 "is_submittable": d.is_submittable, "definition": d.to_dict()}
                                for d in registry.all() if d.app == "company"],
                    "archived": get_setting(COMPANY_DOCTYPES_ARCHIVE_KEY, []) or [],
                    "conflicts": list(getattr(registry, "company_conflicts", []))}
        return run(request, fn)

    @app.post("/api/devtools/objects")
    def company_object_create(request: Request, body: dict = Body(...)):
        def fn():
            require_manager()
            spec = _normalise_company_doctype(body.get("definition") or body)
            definitions = _company_doctypes()
            if any(x.get("name") == spec["name"] for x in definitions):
                raise ValidationError(f"Company DocType {spec['name']!r} already exists")
            if registry.exists(spec["name"]):
                raise ValidationError(f"DocType {spec['name']!r} already exists in an installed application")
            _refuse_shared_table(spec["name"])
            previous = list(definitions)
            definitions.append(spec)
            set_setting(COMPANY_DOCTYPES_KEY, definitions)
            try:
                _activate_company_doctypes(definitions)
                migration = schema.migrate()
            except Exception:
                _activate_company_doctypes(previous)
                raise
            return {"created": spec["name"], "migration": migration}
        return run(request, fn)

    @app.put("/api/devtools/objects/{doctype}")
    def company_object_update(doctype: str, request: Request, body: dict = Body(...)):
        def fn():
            require_manager()
            definitions = _company_doctypes()
            old = next((x for x in definitions if x.get("name") == doctype), None)
            if old is None:
                raise ValidationError("Only company-local DocTypes can be edited here")
            spec = _normalise_company_doctype(body.get("definition") or body, doctype)
            old_fields = {f.get("fieldname"): f for f in old.get("fields", [])}
            new_fields = {f.get("fieldname"): f for f in spec.get("fields", [])}
            for fieldname in old_fields.keys() & new_fields.keys():
                if old_fields[fieldname].get("fieldtype") != new_fields[fieldname].get("fieldtype"):
                    raise ValidationError(f"Changing fieldtype for {fieldname!r} is not supported; add a new field and migrate data explicitly")
            previous = list(definitions)
            definitions = [spec if x.get("name") == doctype else x for x in definitions]
            set_setting(COMPANY_DOCTYPES_KEY, definitions)
            try:
                _activate_company_doctypes(definitions)
                migration = schema.migrate()
            except Exception:
                _activate_company_doctypes(previous)
                raise
            return {"updated": doctype, "migration": migration, "note": "Removed field columns are retained in the database; no stored values were dropped."}
        return run(request, fn)

    @app.post("/api/devtools/objects/{doctype}/restore")
    def company_object_restore(doctype: str, request: Request):
        def fn():
            require_manager()
            definitions = _company_doctypes()
            if any(x.get("name") == doctype for x in definitions) or registry.exists(doctype):
                raise ValidationError(f"DocType {doctype!r} already exists")
            _refuse_shared_table(doctype, archived=(doctype,))
            archive = get_setting(COMPANY_DOCTYPES_ARCHIVE_KEY, []) or []
            index = next((i for i, x in enumerate(archive) if (x.get("definition") or {}).get("name") == doctype), None)
            if index is None:
                raise ValidationError("Archived DocType not found")
            entry = archive.pop(index)
            definitions.append(entry["definition"])
            previous = _company_doctypes()
            set_setting(COMPANY_DOCTYPES_ARCHIVE_KEY, archive)
            set_setting(COMPANY_DOCTYPES_KEY, definitions)
            try:
                _activate_company_doctypes(definitions)
                migration = schema.migrate()
            except Exception:
                _activate_company_doctypes(previous)
                raise
            return {"restored": doctype, "migration": migration}
        return run(request, fn)

    @app.delete("/api/devtools/objects/{doctype}")
    def company_object_delete(doctype: str, request: Request):
        def fn():
            require_manager()
            definitions = _company_doctypes()
            old = next((x for x in definitions if x.get("name") == doctype), None)
            if old is None:
                raise ValidationError("Only company-local DocTypes can be deleted here")
            links = registry.links_to(doctype)
            if links:
                raise ValidationError("Cannot delete this DocType while other DocTypes link to it: " + ", ".join(f"{d.name}.{f.fieldname}" for d, f in links))
            archive = get_setting(COMPANY_DOCTYPES_ARCHIVE_KEY, []) or []
            archive.append({"definition": old, "deleted_on": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
            set_setting(COMPANY_DOCTYPES_ARCHIVE_KEY, archive)
            remaining = [x for x in definitions if x.get("name") != doctype]
            set_setting(COMPANY_DOCTYPES_KEY, remaining)
            _activate_company_doctypes(remaining)
            return {"deleted": doctype, "note": "Metadata archived. The database table and its records were deliberately retained; no data was physically deleted."}
        return run(request, fn)

