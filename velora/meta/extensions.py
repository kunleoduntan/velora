"""Company-local DocType metadata extensions: Custom Fields and Property Setters.

Extensions are stored in the active company's velora_setting table. They are applied
as an overlay to installed-app metadata; app source files are never rewritten.
"""
from __future__ import annotations

from copy import deepcopy
from sqlalchemy import inspect
from fastapi import Body, Request

from .. import db
from ..exceptions import DoesNotExistError, ValidationError
from ..permissions import get_session
from ..settings import get_setting, set_setting
from .spec import DocField, COLUMN_TYPES, FIELDNAME_RE, SYSTEM_FIELDS, CHILD_FIELDS

CUSTOM_FIELDS_PREFIX = "meta.custom_fields."
PROPERTY_SETTERS_PREFIX = "meta.property_setters."
_ALLOWED_PROPERTIES = {
    "label", "required", "read_only", "hidden", "default", "in_list_view",
    "in_standard_filter", "description", "length",
}


def _manager():
    s = get_session()
    if s.user != "Administrator" and "System Manager" not in s.roles:
        from ..exceptions import PermissionDenied
        raise PermissionDenied("Only a System Manager can manage DocType metadata extensions")


def _invalidate():
    site = __import__("velora.site", fromlist=["current"]).current()
    site.metadata_extensions_cache.clear()
    site.reset_tables()


def _load_overlay(doctype: str) -> tuple[list[dict], list[dict]]:
    site = __import__("velora.site", fromlist=["current"]).current()
    cache = site.metadata_extensions_cache
    if doctype not in cache:
        fields = get_setting(CUSTOM_FIELDS_PREFIX + doctype, []) or []
        setters = get_setting(PROPERTY_SETTERS_PREFIX + doctype, []) or []
        cache[doctype] = (fields, setters)
    return cache[doctype]


def effective_meta(base):
    fields, setters = _load_overlay(base.name)
    if not fields and not setters:
        return base
    meta = deepcopy(base)
    existing = {f.fieldname for f in meta.fields}
    for raw in fields:
        if raw.get("fieldname") not in existing:
            raw = dict(raw)
            after = raw.pop("insert_after", None)                           # where in the form the field goes (default: the end)
            new = DocField(**raw)
            at = next((i for i, f in enumerate(meta.fields) if f.fieldname == after), None) if after else None
            if at is None:
                meta.fields.append(new)
            else:
                meta.fields.insert(at + 1, new)
            existing.add(raw["fieldname"])
    by_name = {f.fieldname: f for f in meta.fields}
    for item in setters:
        field = by_name.get(item.get("fieldname"))
        if field and item.get("property") in _ALLOWED_PROPERTIES:
            setattr(field, item["property"], item.get("value"))
    return meta


def list_custom_fields(doctype: str):
    _manager()
    from .registry import registry
    registry.get(doctype)
    return get_setting(CUSTOM_FIELDS_PREFIX + doctype, []) or []


def add_custom_field(doctype: str, data: dict):
    _manager()
    from .registry import registry
    base = registry.get(doctype)
    name = str(data.get("fieldname") or "").strip()
    fieldtype = str(data.get("fieldtype") or "").strip()
    if not FIELDNAME_RE.fullmatch(name):
        raise ValidationError("Fieldname must use lowercase letters, numbers and underscores")
    if name in SYSTEM_FIELDS or name in CHILD_FIELDS or base.get_field(name):
        raise ValidationError(f"Field {name!r} already exists or is reserved")
    # A previously removed Custom Field leaves its physical column/data in place.
    # Do not silently reuse that column for a potentially different SQL type.
    from ..db.tables import table_name
    inspector = inspect(db.get_engine())
    physical_table = table_name(doctype)
    if inspector.has_table(physical_table):
        physical_columns = {c["name"] for c in inspector.get_columns(physical_table)}
        if name in physical_columns:
            raise ValidationError(f"Fieldname {name!r} has a preserved database column; choose a new fieldname")
    if fieldtype not in COLUMN_TYPES:
        raise ValidationError("Custom Fields must use a supported data field type; layout and child-table fields are not supported here")
    options = data.get("options")
    choices = data.get("choices") or []
    if fieldtype == "Select" and not choices:
        choices = [x.strip() for x in str(options or "").split("\n") if x.strip()]
        if not choices:
            raise ValidationError("Select fields require choices")
    if fieldtype == "Link":
        if not options or not registry.exists(str(options)):
            raise ValidationError("Link fields must reference an installed DocType")
    length = data.get("length")
    if length is not None and (not isinstance(length, int) or length < 1 or length > 10000):
        raise ValidationError("Field length must be between 1 and 10000")
    field = {
        "fieldname": name, "fieldtype": fieldtype,
        "label": str(data.get("label") or name.replace("_", " ").title()),
        "options": str(options) if fieldtype == "Link" else None,
        "choices": choices if fieldtype == "Select" else [],
        "required": bool(data.get("required")), "unique": bool(data.get("unique")),
        "default": data.get("default"), "read_only": bool(data.get("read_only")),
        "hidden": bool(data.get("hidden")), "in_list_view": bool(data.get("in_list_view")),
        "in_standard_filter": bool(data.get("in_standard_filter")), "json_index": False,
        "length": length, "description": str(data.get("description") or ""),
    }
    after = str(data.get("insert_after") or "").strip()
    if after:
        known = {f.fieldname for f in base.fields} | {f["fieldname"] for f in list_custom_fields(doctype)}
        if after not in known:
            raise ValidationError(f"Insert After: there is no field called {after!r}")
        field["insert_after"] = after
    values = list_custom_fields(doctype)
    values.append(field)
    set_setting(CUSTOM_FIELDS_PREFIX + doctype, values)
    _invalidate()
    # Add the physical column now; existing records remain intact and NULL until populated.
    from ..db.schema import migrate
    migrate()
    return field


def delete_custom_field(doctype: str, fieldname: str):
    _manager()
    values = list_custom_fields(doctype)
    new_values = [x for x in values if x.get("fieldname") != fieldname]
    if len(new_values) == len(values):
        raise DoesNotExistError(f"Custom Field {fieldname!r} does not exist")
    set_setting(CUSTOM_FIELDS_PREFIX + doctype, new_values)
    # Preserve the physical database column and its data. Removal is metadata-only;
    # destructive column deletion requires an explicit data migration.
    setters = get_setting(PROPERTY_SETTERS_PREFIX + doctype, []) or []
    set_setting(PROPERTY_SETTERS_PREFIX + doctype, [x for x in setters if x.get("fieldname") != fieldname])
    _invalidate()
    return {"deleted": fieldname, "data_preserved": True}


def list_property_setters(doctype: str):
    _manager()
    from .registry import registry
    registry.get(doctype)
    return get_setting(PROPERTY_SETTERS_PREFIX + doctype, []) or []


def save_property_setter(doctype: str, data: dict):
    _manager()
    from .registry import registry
    meta = registry.get(doctype)
    fieldname, prop = str(data.get("fieldname") or ""), str(data.get("property") or "")
    field = meta.get_field(fieldname)
    if not field:
        raise ValidationError(f"Field {fieldname!r} does not exist on {doctype}")
    if prop not in _ALLOWED_PROPERTIES:
        raise ValidationError(f"Property {prop!r} cannot be overridden")
    value = data.get("value")
    if prop in {"required", "read_only", "hidden", "in_list_view", "in_standard_filter"} and not isinstance(value, bool):
        raise ValidationError(f"Property {prop} requires a boolean value")
    if prop == "length" and value is not None and (not isinstance(value, int) or value < 1 or value > 10000):
        raise ValidationError("Length must be between 1 and 10000")
    if prop in {"label", "description"} and not isinstance(value, str):
        raise ValidationError(f"Property {prop} requires text")
    values = list_property_setters(doctype)
    values = [x for x in values if not (x.get("fieldname") == fieldname and x.get("property") == prop)]
    values.append({"fieldname": fieldname, "property": prop, "value": value})
    set_setting(PROPERTY_SETTERS_PREFIX + doctype, values)
    _invalidate()
    from ..db.schema import migrate
    migrate()
    return {"fieldname": fieldname, "property": prop, "value": value}


def delete_property_setter(doctype: str, fieldname: str, prop: str):
    _manager()
    values = list_property_setters(doctype)
    new_values = [x for x in values if not (x.get("fieldname") == fieldname and x.get("property") == prop)]
    if len(new_values) == len(values):
        raise DoesNotExistError("Property Setter does not exist")
    set_setting(PROPERTY_SETTERS_PREFIX + doctype, new_values)
    _invalidate()
    return {"reset": {"fieldname": fieldname, "property": prop}}



def export_metadata_extensions():
    """Portable, company-local customization package (no business records)."""
    _manager()
    from .registry import registry
    exported = {}
    for meta in registry.all():
        fields = get_setting(CUSTOM_FIELDS_PREFIX + meta.name, []) or []
        setters = get_setting(PROPERTY_SETTERS_PREFIX + meta.name, []) or []
        if fields or setters:
            exported[meta.name] = {"custom_fields": fields, "property_setters": setters}
    return {"format": "velora-metadata-extensions", "version": 1, "doctypes": exported}


def import_metadata_extensions(package: dict):
    """Merge a customization package into this company after validating all references."""
    _manager()
    from .registry import registry
    if not isinstance(package, dict) or package.get("format") != "velora-metadata-extensions" or package.get("version") != 1:
        raise ValidationError("Unsupported metadata extension package")
    doctypes = package.get("doctypes")
    if not isinstance(doctypes, dict):
        raise ValidationError("Package doctypes must be an object")
    # Validate the entire package before writing any settings.
    planned = []
    for doctype, spec in doctypes.items():
        registry.get(doctype)  # validate existence against the active app registry
        base = registry._doctypes[doctype]  # raw app metadata, before company overlays
        if not isinstance(spec, dict):
            raise ValidationError(f"Invalid metadata extension entry for {doctype}")
        incoming_fields = spec.get("custom_fields", [])
        incoming_setters = spec.get("property_setters", [])
        if not isinstance(incoming_fields, list) or not isinstance(incoming_setters, list):
            raise ValidationError(f"Custom Fields and Property Setters for {doctype} must be lists")
        app_names = {f.fieldname for f in base.fields}
        existing_custom_list = get_setting(CUSTOM_FIELDS_PREFIX + doctype, []) or []
        existing_custom_map = {x.get("fieldname"): x for x in existing_custom_list}
        names = app_names | set(existing_custom_map)
        incoming_seen = set()
        from ..db.tables import table_name
        inspector = inspect(db.get_engine())
        physical_table = table_name(doctype)
        physical_columns = {c["name"] for c in inspector.get_columns(physical_table)} if inspector.has_table(physical_table) else set()
        for field in incoming_fields:
            if not isinstance(field, dict):
                raise ValidationError(f"Invalid Custom Field entry for {doctype}")
            name = field.get("fieldname")
            if name in app_names:
                raise ValidationError(f"Imported Custom Field {doctype}.{name} conflicts with app metadata")
            # Validate by the same rules as interactive creation, without mutating the DB.
            if not isinstance(name, str) or not FIELDNAME_RE.fullmatch(name) or name in SYSTEM_FIELDS or name in CHILD_FIELDS:
                raise ValidationError(f"Invalid imported fieldname on {doctype}: {name!r}")
            if name in incoming_seen:
                raise ValidationError(f"Duplicate imported Custom Field {doctype}.{name}")
            if field.get("fieldtype") not in COLUMN_TYPES:
                raise ValidationError(f"Unsupported imported field type on {doctype}.{name}")
            if field.get("fieldtype") == "Link" and not registry.exists(str(field.get("options") or "")):
                raise ValidationError(f"Imported Link field {doctype}.{name} targets an unknown DocType")
            if field.get("fieldtype") == "Select" and not field.get("choices"):
                raise ValidationError(f"Imported Select field {doctype}.{name} has no choices")
            if name in existing_custom_map:
                if existing_custom_map[name] != field:
                    raise ValidationError(f"Imported Custom Field {doctype}.{name} conflicts with an existing company field")
            elif name in physical_columns:
                raise ValidationError(f"Imported fieldname {doctype}.{name} has a preserved database column; choose a new fieldname")
            incoming_seen.add(name)
            names.add(name)
        for setter in incoming_setters:
            if not isinstance(setter, dict) or setter.get("fieldname") not in names or setter.get("property") not in _ALLOWED_PROPERTIES:
                raise ValidationError(f"Invalid Property Setter for {doctype}: {setter}")
            prop, value = setter["property"], setter.get("value")
            if prop in {"required", "read_only", "hidden", "in_list_view", "in_standard_filter"} and not isinstance(value, bool):
                raise ValidationError(f"Imported Property Setter {doctype}.{setter['fieldname']}.{prop} requires a boolean")
            if prop == "length" and value is not None and (not isinstance(value, int) or value < 1 or value > 10000):
                raise ValidationError(f"Imported Property Setter {doctype}.{setter['fieldname']}.length is invalid")
            if prop in {"label", "description"} and not isinstance(value, str):
                raise ValidationError(f"Imported Property Setter {doctype}.{setter['fieldname']}.{prop} requires text")
        planned.append((doctype, incoming_fields, incoming_setters))
    # Merge definitions; do not silently remove local customizations omitted from the package.
    for doctype, incoming_fields, incoming_setters in planned:
        old_fields = get_setting(CUSTOM_FIELDS_PREFIX + doctype, []) or []
        field_map = {x["fieldname"]: x for x in old_fields}
        field_map.update({x["fieldname"]: x for x in incoming_fields})
        set_setting(CUSTOM_FIELDS_PREFIX + doctype, list(field_map.values()))
        old_setters = get_setting(PROPERTY_SETTERS_PREFIX + doctype, []) or []
        setter_map = {(x["fieldname"], x["property"]): x for x in old_setters}
        setter_map.update({(x["fieldname"], x["property"]): x for x in incoming_setters})
        set_setting(PROPERTY_SETTERS_PREFIX + doctype, list(setter_map.values()))
    _invalidate()
    from ..db.schema import migrate
    migrate()
    return {"imported_doctypes": [x[0] for x in planned], "custom_fields": sum(len(x[1]) for x in planned),
            "property_setters": sum(len(x[2]) for x in planned)}

def install_routes(app, scope, run):
    @app.get("/api/custom-fields/{doctype}")
    def get_custom_fields(doctype: str, request: Request):
        return run(request, lambda: list_custom_fields(doctype))
    @app.post("/api/custom-fields/{doctype}")
    def post_custom_field(doctype: str, request: Request, body: dict = Body(...)):
        return run(request, lambda: add_custom_field(doctype, body))
    @app.delete("/api/custom-fields/{doctype}/{fieldname}")
    def remove_custom_field(doctype: str, fieldname: str, request: Request):
        return run(request, lambda: delete_custom_field(doctype, fieldname))
    @app.get("/api/property-setters/{doctype}")
    def get_property_setters(doctype: str, request: Request):
        return run(request, lambda: list_property_setters(doctype))
    @app.post("/api/property-setters/{doctype}")
    def post_property_setter(doctype: str, request: Request, body: dict = Body(...)):
        return run(request, lambda: save_property_setter(doctype, body))
    @app.delete("/api/property-setters/{doctype}/{fieldname}/{prop}")
    def remove_property_setter(doctype: str, fieldname: str, prop: str, request: Request):
        return run(request, lambda: delete_property_setter(doctype, fieldname, prop))
    @app.get("/api/metadata-extensions/export")
    def export_extensions(request: Request):
        return run(request, export_metadata_extensions)
    @app.post("/api/metadata-extensions/import")
    def import_extensions(request: Request, body: dict = Body(...)):
        return run(request, lambda: import_metadata_extensions(body))
