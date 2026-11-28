"""The DocType metadata specification (v1) and its validator.

A DocType JSON file is the single source of truth for: the database table,
the API shape, the form/list UI, permissions and the lifecycle flags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import BigInteger, Date, DateTime, Numeric, SmallInteger, String, Text, Float

from ..db.types import json_type

from ..exceptions import MetaError
from .conditions import validate_condition

SPEC_VERSION = 1

# fieldtype -> SQLAlchemy type factory (None = layout only, no column / child rows)
COLUMN_TYPES = {
    "Data": lambda f: String(f.length or 255),
    "Text": lambda f: Text(),
    "Int": lambda f: BigInteger(),
    "Float": lambda f: Float(),
    "Currency": lambda f: Numeric(21, 6),
    "Check": lambda f: SmallInteger(),
    "Date": lambda f: Date(),
    "Datetime": lambda f: DateTime(),
    "Select": lambda f: String(140),
    "Link": lambda f: String(255),
    "JSON": lambda f: json_type(),
}
LAYOUT_TYPES = {"Section Break", "Column Break", "Tab Break"}
TABLE_TYPE = "Table"
ALL_TYPES = set(COLUMN_TYPES) | LAYOUT_TYPES | {TABLE_TYPE}

SYSTEM_FIELDS = ("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx")
CHILD_FIELDS = ("parent", "parenttype", "parentfield")
PERM_TYPES = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "import", "share", "print", "email")

FIELDNAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SERIES_RE = re.compile(r"^series:(?P<prefix>.*)\.(?P<hashes>#+)$")


_LINK_OPS = {"=", "!=", "in", "not in", ">", "<", ">=", "<=", "like"}


def _link_filters(raw, where, err) -> list:
    out = []
    for flt in raw or []:
        if not (isinstance(flt, (list, tuple)) and len(flt) == 3 and FIELDNAME_RE.match(str(flt[0])) and str(flt[1]).lower() in _LINK_OPS):
            err(f"{where}: link_filters entries must be [field, operator, value]")
            continue
        out.append([str(flt[0]), str(flt[1]).lower(), flt[2]])
    return out


@dataclass
class DocField:
    fieldname: str
    fieldtype: str
    label: str = ""
    options: str | None = None          # Link/Table target doctype
    choices: list = field(default_factory=list)  # Select options
    required: bool = False
    unique: bool = False
    default: object = None
    read_only: bool = False
    hidden: bool = False
    permlevel: int = 0
    in_list_view: bool = False
    in_standard_filter: bool = False
    json_index: bool = False            # JSON fields on PostgreSQL: a GIN index so json_contains / json_has_key filters are fast
    length: int | None = None
    description: str = ""
    depends_on: str = ""
    mandatory_depends_on: str = ""
    read_only_depends_on: str = ""
    fetch_from: str = ""                # "<link field>.<field of the linked document>": copied when the link is set (ERPNext-style fetch)
    link_filters: list = field(default_factory=list)   # Link only: [[field, op, value], ...] the picker applies and the server enforces ("only posting accounts")

    @property
    def is_layout(self):
        return self.fieldtype in LAYOUT_TYPES

    @property
    def is_table(self):
        return self.fieldtype == TABLE_TYPE

    @property
    def has_column(self):
        return self.fieldtype in COLUMN_TYPES

    def to_dict(self):
        # layout breaks keep exactly the label the author gave (an unlabeled break shows no heading)
        label = self.label if self.is_layout else (self.label or self.fieldname.replace("_", " ").title())
        d = {"fieldname": self.fieldname, "fieldtype": self.fieldtype, "label": label}
        for k in ("options", "required", "unique", "default", "read_only", "hidden", "permlevel", "in_list_view", "in_standard_filter", "json_index", "length", "description", "depends_on", "mandatory_depends_on", "read_only_depends_on", "fetch_from"):
            v = getattr(self, k)
            if v not in (None, False, ""):
                d[k] = v
        if self.link_filters:
            d["link_filters"] = self.link_filters
        if self.fieldtype == "Select":
            d["options"] = self.choices
        return d


@dataclass
class DocPerm:
    role: str
    permlevel: int = 0
    read: bool = False
    write: bool = False
    create: bool = False
    delete: bool = False
    submit: bool = False
    cancel: bool = False
    export: bool = False
    amend: bool = False
    report: bool = False
    import_: bool = False
    share: bool = False
    print: bool = False
    email: bool = False

    def allows(self, ptype: str) -> bool:
        return bool(getattr(self, "import_" if ptype == "import" else ptype, False))


@dataclass
class DocType:
    name: str
    module: str = ""
    app: str = ""
    fields: list = field(default_factory=list)
    permissions: list = field(default_factory=list)
    autoname: str | None = None          # None|hash | prompt | field:<f> | series:<PREFIX>.####
    title_field: str | None = None
    image_field: str | None = None       # a Data field holding the id of an attached image, shown as a photo at the top of the form
    is_submittable: bool = False
    istable: bool = False
    track_changes: bool = False
    hide_from_menu: bool = False        # a system record (kept in the database, shown in no sidebar or list of documents)
    sort_field: str = "modified"
    sort_order: str = "desc"
    description: str = ""
    layout: dict | None = None           # optional 12-column form layout (see velora.meta.layout)
    grid_columns: list | None = None     # child tables: unbounded ordered visible columns with independent widths
    controller_module: str = ""          # dotted path, filled by the registry
    source: str = ""                     # file it was loaded from

    @property
    def directory(self):
        from pathlib import Path
        return Path(self.source).parent if self.source else None

    # ---- convenience views over the fields ---------------------------------
    @property
    def value_fields(self):
        return [f for f in self.fields if f.has_column]

    @property
    def table_fields(self):
        return [f for f in self.fields if f.is_table]

    @property
    def system_columns(self):
        return SYSTEM_FIELDS + (CHILD_FIELDS if self.istable else ())

    def get_field(self, fieldname):
        return next((f for f in self.fields if f.fieldname == fieldname), None)

    def column_names(self):
        return list(self.system_columns) + [f.fieldname for f in self.value_fields]

    def to_dict(self):
        """Shape served to the UI by /api/meta/{doctype}."""
        return {
            "spec_version": SPEC_VERSION, "name": self.name, "module": self.module, "app": self.app,
            "autoname": self.autoname, "title_field": self.title_field, "image_field": self.image_field,
            "is_submittable": self.is_submittable, "istable": self.istable,
            "track_changes": self.track_changes, "hide_from_menu": self.hide_from_menu, "sort_field": self.sort_field,
            "sort_order": self.sort_order, "fields": [f.to_dict() for f in self.fields],
            **({"layout": self.layout} if self.layout else {}), **({"grid_columns": self.grid_columns} if self.grid_columns else {}),
        }

    # ---- parsing & validation ---------------------------------------------
    @classmethod
    def from_dict(cls, data: dict, app: str = "", source: str = "") -> "DocType":
        errors: list[str] = []
        name = data.get("name") or data.get("doctype")
        if not name or not isinstance(name, str):
            raise MetaError(f"{source}: DocType needs a 'name'")

        def err(msg):
            errors.append(msg)

        fields, seen = [], set()
        for i, raw in enumerate(data.get("fields", [])):
            ft = raw.get("fieldtype")
            fn = raw.get("fieldname")
            where = f"field #{i + 1} ({fn or '?'})"
            if ft not in ALL_TYPES:
                err(f"{where}: unknown fieldtype {ft!r}")
                continue
            if ft in LAYOUT_TYPES:
                fn = fn or f"{ft.lower().replace(' ', '_')}_{i}"
            elif not fn or not FIELDNAME_RE.match(fn):
                err(f"{where}: invalid fieldname (lowercase letters, digits, underscore)")
                continue
            if fn in seen:
                err(f"{where}: duplicate fieldname")
                continue
            seen.add(fn)
            if fn in SYSTEM_FIELDS or fn in CHILD_FIELDS:
                err(f"{where}: collides with a system field")
            choices, options = [], raw.get("options")
            if ft == "Select":
                opts = options if isinstance(options, list) else str(options or "").split("\n")
                choices = [str(o).strip() for o in opts if str(o).strip()]
                options = None
                if not choices:
                    err(f"{where}: Select needs options")
            if ft in ("Link", TABLE_TYPE) and not options:
                err(f"{where}: {ft} needs 'options' (target DocType)")
            for condition_key in ("depends_on", "mandatory_depends_on", "read_only_depends_on"):
                try:
                    validate_condition(raw.get(condition_key))
                except ValueError as exc:
                    err(f"{where}: {exc}")
            level = raw.get("permlevel", 0)
            if not isinstance(level, int) or isinstance(level, bool) or level < 0:
                err(f"{where}: permlevel must be a non-negative integer")
                level = 0
            fields.append(DocField(
                fieldname=fn, fieldtype=ft, label=raw.get("label", ""), options=options if ft in ("Link", TABLE_TYPE) else None,
                choices=choices, required=bool(raw.get("required")), unique=bool(raw.get("unique")),
                default=raw.get("default"), read_only=bool(raw.get("read_only")), hidden=bool(raw.get("hidden")),
                permlevel=level,
                in_list_view=bool(raw.get("in_list_view")), in_standard_filter=bool(raw.get("in_standard_filter")), json_index=bool(raw.get("json_index")), length=raw.get("length"),
                description=raw.get("description", ""),
                depends_on=str(raw.get("depends_on") or ""), mandatory_depends_on=str(raw.get("mandatory_depends_on") or ""),
                read_only_depends_on=str(raw.get("read_only_depends_on") or ""),
                fetch_from=str(raw.get("fetch_from") or ""),
                link_filters=_link_filters(raw.get("link_filters"), where, err) if ft == "Link" else [],
            ))

        perms = []
        for p in data.get("permissions", []):
            if not p.get("role"):
                err("permission entry without 'role'")
                continue
            level = p.get("permlevel", 0)
            if not isinstance(level, int) or isinstance(level, bool) or level < 0:
                err(f"permission for role {p['role']!r}: permlevel must be a non-negative integer")
                continue
            perms.append(DocPerm(role=p["role"], permlevel=level, **{("import_" if k == "import" else k): bool(p.get(k)) for k in PERM_TYPES}))

        dt = cls(
            name=name, module=data.get("module", ""), app=app, fields=fields, permissions=perms,
            autoname=data.get("autoname"), title_field=data.get("title_field"), image_field=data.get("image_field"),
            is_submittable=bool(data.get("is_submittable")), istable=bool(data.get("istable")),
            track_changes=bool(data.get("track_changes")), hide_from_menu=bool(data.get("hide_from_menu")), sort_field=data.get("sort_field", "modified"),
            sort_order=data.get("sort_order", "desc"), description=data.get("description", ""), source=source,
        )

        if dt.is_submittable and not dt.istable and "amended_from" not in seen:
            dt.fields.append(DocField(fieldname="amended_from", fieldtype="Link", options=name, label="Amended From", read_only=True, hidden=True,
                                   description="The cancelled document this one amends (set by Amend)."))
        if dt.is_submittable and not dt.istable and "workflow_state" not in seen:
            # Every submittable document can take an approval workflow without Customize Form: the workflow keeps its state here.
            dt.fields.append(DocField(fieldname="workflow_state", fieldtype="Data", label="Workflow State", read_only=True, hidden=True,
                                   description="Set by the approval workflow, when one is switched on for this document type."))
        if dt.istable and dt.is_submittable:
            err("a child table (istable) cannot be submittable")
        if dt.istable and dt.autoname not in (None, "hash"):
            err("child tables always use hash naming")
        if dt.title_field and dt.title_field not in seen:
            err(f"title_field {dt.title_field!r} is not a field")
        if dt.image_field and dt.image_field not in seen:
            err(f"image_field {dt.image_field!r} is not a field")
        for f in dt.fields:
            if f.fetch_from:
                link, _, target = f.fetch_from.partition(".")
                src = dt.get_field(link)
                if not src or src.fieldtype != "Link" or not target:
                    err(f"{name}.{f.fieldname}: fetch_from must be '<Link field>.<field>' naming a Link field of this DocType")
        if dt.sort_order not in ("asc", "desc"):
            err("sort_order must be 'asc' or 'desc'")
        if dt.sort_field not in dt.column_names():
            err(f"sort_field {dt.sort_field!r} is not a column")
        a = dt.autoname
        if a and a not in ("hash", "prompt"):
            if a.startswith("field:"):
                f = dt.get_field(a[6:])
                if not f or not f.has_column:
                    err(f"autoname {a!r} refers to a missing field")
                else:
                    f.required = True
                    f.unique = True
            elif not SERIES_RE.match(a):
                err(f"autoname {a!r} is not hash | prompt | field:<name> | series:<PREFIX>.####")
        from . import layout as lay
        if data.get("layout") is not None:
            if dt.istable:
                err("a child table has no 'layout': use 'grid_columns' to choose its grid columns")
            else:
                errs = lay.validate_layout(data["layout"], dt)
                errors.extend(f"layout: {e}" for e in errs)
                if not errs:
                    dt.layout = lay.normalize_layout(data["layout"])
        if data.get("grid_columns") is not None:
            if not dt.istable:
                err("'grid_columns' is only for child tables (istable); use 'layout' for forms")
            else:
                errs = lay.validate_grid_columns(data["grid_columns"], dt)
                errors.extend(f"grid_columns: {e}" for e in errs)
                if not errs:
                    dt.grid_columns = lay.normalize_grid_columns(data["grid_columns"])
        if errors:
            raise MetaError(f"Invalid DocType {name!r} ({source}):\n  - " + "\n  - ".join(errors), details=errors)
        return dt
