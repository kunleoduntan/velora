"""DocType Creator: create DocTypes (as real, version-controlled app files) from pasted JSON.

Accepts three shapes - {"doctypes": [...]}, one DocType definition, or just a list of fields (name/module then come from the options) -
in EITHER dialect: Velora's own, or a Frappe DocType export (`reqd`, `field_order`, `naming_series`, "Small Text" ...). Frappe-only features are mapped
where Velora has an equivalent and REPORTED as warnings where it does not - nothing is dropped silently.

Safety (each point is a lesson from the Frappe tool this replaces: debug pop-ups, half-created sets, a checkbox that creates on save):
  * everything is validated TOGETHER first (each DocType, then the links between them and the DocTypes that already exist) - all problems reported at once
  * nothing is written unless everything is valid; the write itself is all-or-nothing (a failure removes what it had written)
  * an existing DocType is a conflict you choose how to handle (`error` or `skip`), never silently overwritten
  * it only writes inside the app you name, and only inside a doctype/<snake_name>/ folder
"""
from __future__ import annotations

import importlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..exceptions import MetaError
from ..meta.registry import cross_check, pascal, registry
from ..meta.spec import FIELDNAME_RE, LAYOUT_TYPES, PERM_TYPES, DocType
from ..scaffold import DOCTYPE_NAME_RE, snake

# ---- Frappe -> Velora field types ---------------------------------------------------------------------------------
SAME = {"Data", "Text", "Int", "Float", "Currency", "Check", "Date", "Datetime", "Select", "Link", "JSON", "Table", "Section Break", "Column Break", "Tab Break"}
TEXT = {"Small Text", "Long Text", "Text Editor", "Markdown Editor", "HTML Editor", "Code"}
DATA = {"Phone", "Barcode", "Color", "Attach", "Attach Image", "Autocomplete", "Read Only", "Icon", "Signature", "Image"}
DISPLAY_ONLY = {"Button", "Heading", "HTML", "Fold"}
APPROX = {  # fieldtype -> (velora type, why it is only an approximation)
    "Percent": ("Float", None), "Rating": ("Float", "stored as a number"), "Duration": ("Int", "stored as seconds"), "Time": ("Data", "stored as text (HH:MM:SS)"),
    "Password": ("Data", "stored as PLAIN text - do not use for secrets"), "Dynamic Link": ("Data", "not validated against a DocType (use a Link or a client script)"),
    "Geolocation": ("JSON", None), "Table MultiSelect": ("JSON", "stored as a JSON list, not a child table"),
}
UNSUPPORTED_KEYS = {"fetch_from": "fetch_from", "allow_on_submit": "allow_on_submit", "permlevel": "permission levels"}


@dataclass
class Plan:
    structure: str = "unknown"
    specs: list = field(default_factory=list)          # Velora-dialect dicts, ready to write
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    writes: list = field(default_factory=list)         # (name, path) in dependency order: child tables first

    def report(self) -> dict:
        return {"structure": self.structure, "ok": not self.errors, "errors": self.errors, "warnings": self.warnings, "conflicts": self.conflicts,
                "skipped": self.skipped,
                "doctypes": [{"name": s["name"], "module": s["module"], "fields": len(s["fields"]), "child": bool(s.get("istable")),
                              "submittable": bool(s.get("is_submittable")), "links": sorted({f["options"] for f in s["fields"] if f["fieldtype"] in ("Link", "Table")}),
                              "path": str(dict(self.writes).get(s["name"], ""))} for s in self.specs],
                "order": [n for n, _ in self.writes]}


def detect_structure(data) -> str:
    if isinstance(data, dict):
        if isinstance(data.get("doctypes"), list):
            return "multiple"
        if isinstance(data.get("fields"), list) or data.get("doctype") == "DocType":
            return "single"
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data) and any("fieldname" in x or "fieldtype" in x for x in data):
        return "fields"
    return "unknown"


def _flag(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes")
    return bool(v)


def _default(ft: str, v):
    if v in (None, ""):
        return None
    if ft == "Check":
        return 1 if _flag(v) else 0
    if ft in ("Int", "Float", "Currency", "Percent"):
        try:
            return int(v) if ft == "Int" else float(v)
        except (TypeError, ValueError):
            return None
    return v


_DATE_TOKENS = {"YYYY", "YY", "MM", "DD", "FY", "yyyy", "yy"}


def _series_parts(series: str) -> tuple[str, int, bool]:
    """'SINV-.YYYY.-.#####' -> ('SINV', 5, True): literal prefix, number of digits, and whether date tokens were dropped."""
    prefix, width, dated = "", 5, False
    for tok in series.split("."):
        if re.fullmatch(r"#+", tok):
            width = len(tok)
        elif tok in _DATE_TOKENS:
            dated = True
        else:
            prefix += tok
    return re.sub(r"[^A-Za-z0-9_]+", "-", prefix).strip("-") if prefix.strip("-_ ") else "", width, dated


def _autoname(defn: dict, fields: list, name: str, warn) -> tuple[str | None, list]:
    a = (defn.get("autoname") or "").strip()
    if not a or a.lower() == "hash":
        return (None if not a else "hash"), fields
    if a.lower() == "prompt":
        return "prompt", fields
    if a.startswith("field:"):
        return a, fields
    if a.startswith("naming_series:"):
        ns = next((f for f in fields if f.get("fieldname") == "naming_series"), None)
        opts = (ns or {}).get("options")                                       # already a list: convert() turned the Select options into one
        first = str(opts[0] if isinstance(opts, list) and opts else opts or "").split("\n")[0].strip()
        prefix, width, dated = _series_parts(first)
        if not prefix:
            prefix = re.sub(r"[^A-Za-z0-9]", "", name)[:4].upper() or "DOC"
        if dated:
            warn(f"{name}: date parts in the naming series {first!r} were dropped (documents are numbered {prefix}-{'0' * (width - 1)}1, ...)")
        warn(f"{name}: the naming_series field was removed (Velora numbers documents itself)")
        return f"series:{prefix}-.{'#' * width}", [f for f in fields if f.get("fieldname") != "naming_series"]
    m = re.match(r"^format:([A-Za-z0-9_\-]*)\{(#+)\}\s*$", a)                        # only a plain prefix: {YYYY}/{MM} style formats cannot be expressed
    if m:
        return f"series:{m.group(1).rstrip('-.') or 'DOC'}-.{m.group(2)}", fields
    warn(f"{name}: naming rule {a!r} is not supported; documents get hash names")
    return None, fields


def convert(defn: dict, *, module: str | None = None, name: str | None = None, flags: dict | None = None) -> tuple[dict, list[str]]:
    """One definition (either dialect) -> a Velora DocType dict, plus warnings. Raises MetaError for things that cannot be mapped at all."""
    flags, warnings = flags or {}, []
    dname = defn.get("name") or name or flags.get("doctype_name")
    warn = warnings.append
    if not dname:
        raise MetaError("A DocType needs a name")
    if _flag(defn.get("issingle", flags.get("is_single"))):
        raise MetaError(f"{dname}: Single DocTypes (one-record settings pages) are not supported. Use a normal DocType, or store settings with velora.settings.")
    istable = _flag(defn.get("istable", flags.get("is_child")))
    submittable = _flag(defn.get("is_submittable", flags.get("is_submittable")))
    order = defn.get("field_order") or []
    raw = list(defn.get("fields") or [])
    if order:                                                                  # Frappe exports `fields` in storage order; the real order is field_order
        pos = {n: i for i, n in enumerate(order)}
        raw.sort(key=lambda f: pos.get(f.get("fieldname"), len(pos)))
    fields: list[dict] = []
    for i, f in enumerate(raw, 1):
        ft, fn = f.get("fieldtype"), (f.get("fieldname") or "").strip()
        where = f"{dname}.{fn or f'field #{i}'}"
        if ft in DISPLAY_ONLY:
            warn(f"{where}: {ft} fields are display-only and were skipped (add them with a client script)")
            continue
        if ft in TEXT:
            if ft != "Small Text" and ft != "Long Text":
                warn(f"{where}: {ft} is stored as plain Text")
            ft = "Text"
        elif ft in DATA:
            ft = "Data"
        elif ft in APPROX:
            new, why = APPROX[ft]
            if why:
                warn(f"{where}: {ft} -> {new} ({why})")
            ft = new
        elif ft not in SAME:
            warn(f"{where}: unknown field type {ft!r}, stored as Data")
            ft = "Data"
        if ft in LAYOUT_TYPES:
            fields.append({"fieldname": fn or f"{ft.lower().replace(' ', '_')}_{i}", "fieldtype": ft, **({"label": f["label"]} if f.get("label") else {})})
            continue
        if fn != fn.lower() and FIELDNAME_RE.match(fn.lower()):
            fn = fn.lower()
        out = {"fieldname": fn, "fieldtype": ft}
        if f.get("label"):
            out["label"] = f["label"]
        opts = f.get("options")
        if ft == "Select":
            out["options"] = opts if isinstance(opts, list) else [o.strip() for o in str(opts or "").split("\n") if o.strip()]
        elif ft in ("Link", "Table") and opts:
            out["options"] = opts
        elif opts and ft in ("Data", "Text") and f.get("fieldtype") in ("Data", "Small Text"):
            pass                                                                # Frappe uses Data.options for Email/URL/Phone validation: not needed here
        for src, dst in (("reqd", "required"), ("required", "required"), ("unique", "unique"), ("read_only", "read_only"), ("hidden", "hidden"),
                         ("in_list_view", "in_list_view"), ("in_standard_filter", "in_standard_filter")):
            if _flag(f.get(src)):
                out[dst] = True
        d = _default(f.get("fieldtype") if f.get("fieldtype") == "Percent" else ft, f.get("default"))
        if d is not None:
            out["default"] = d
        for k in ("length", "description"):
            if f.get(k):
                out[k] = f[k]
        for k in ("depends_on", "mandatory_depends_on", "read_only_depends_on"):
            if f.get(k):
                out[k] = str(f[k])
        for k, what in UNSUPPORTED_KEYS.items():
            if f.get(k) and f.get(k) != 0:
                warn(f"{where}: {what} ({k}) is not supported yet - use a client script")
        fields.append(out)
    autoname, fields = _autoname(defn, fields, dname, warn)
    if not autoname and not istable and flags.get("is_autoname") and flags.get("autoname_field_name"):
        autoname = f"field:{flags['autoname_field_name']}"
    perms = []
    for p in defn.get("permissions") or []:
        if p.get("permlevel") not in (None, 0, "0"):
            warn(f"{dname}: permission level {p.get('permlevel')} rows are not supported and were skipped")
            continue
        if p.get("role"):
            perms.append({"role": p["role"], **{k: True for k in PERM_TYPES if _flag(p.get(k))}})
    if not perms and not istable:
        perms = [{"role": "System Manager", "read": True, "write": True, "create": True, "delete": True, "export": True, **({"submit": True, "cancel": True} if submittable else {})}]
    spec = {"name": dname, "module": defn.get("module") or module or flags.get("module") or "", "fields": fields}
    if autoname and not istable:
        spec["autoname"] = autoname
    if istable:
        spec["istable"] = True
    if submittable and not istable:
        spec["is_submittable"] = True
    if _flag(defn.get("track_changes", flags.get("track_changes"))) and not istable:
        spec["track_changes"] = True
    for k in ("title_field", "sort_field", "description"):
        if defn.get(k):
            spec[k] = defn[k]
    if defn.get("sort_order"):
        so = str(defn["sort_order"]).strip().lower()                           # Frappe writes "DESC"/"ASC"
        if so in ("asc", "desc"):
            spec["sort_order"] = so
        else:
            warn(f"{dname}: sort order {defn['sort_order']!r} is not asc/desc and was ignored")
    if perms:
        spec["permissions"] = perms
    for k in ("layout", "grid_columns"):
        if defn.get(k) is not None:
            spec[k] = defn[k]
    return spec, warnings


# ---- app location -----------------------------------------------------------------------------------------------------------
def app_root(app: str) -> Path:
    """The repository folder of an installed/importable app (the folder that CONTAINS the package)."""
    try:
        pkg = Path(importlib.import_module(app).__file__).parent
    except ImportError:
        raise MetaError(f"App {app!r} is not importable; is it in this workspace and listed in config/apps.txt?") from None
    return pkg.parent


def _target(app_dir: Path, app: str, spec: dict) -> Path:
    mod = snake(spec["module"])
    return app_dir / app / mod / "doctype" / snake(spec["name"])


# ---- plan: validate everything, write nothing --------------------------------------------------------------------------------
def plan(data, *, app: str, module: str | None = None, name: str | None = None, flags: dict | None = None, on_conflict: str = "error") -> Plan:
    p = Plan(structure=detect_structure(data))
    if on_conflict not in ("error", "skip"):
        raise MetaError("on_conflict must be 'error' or 'skip'")
    if p.structure == "unknown":
        p.errors.append("Unrecognised JSON. Expected {\"doctypes\": [...]}, one DocType definition with a 'fields' list, or a list of fields.")
        return p
    defs = data["doctypes"] if p.structure == "multiple" else [data] if p.structure == "single" else [{"fields": data}]
    if not defs:
        p.errors.append("No DocTypes found in the JSON")
        return p
    if len(defs) > 100:
        p.errors.append("At most 100 DocTypes per run")
        return p
    try:
        base = app_root(app)
    except MetaError as e:
        p.errors.append(str(e))
        return p
    flags = flags or {}
    # 1. convert + parse each one on its own (every error, not just the first)
    parsed: dict[str, DocType] = {}
    seen_names: set[str] = set()
    for i, d in enumerate(defs, 1):
        if not isinstance(d, dict):
            p.errors.append(f"DocType #{i}: must be an object")
            continue
        try:
            spec, warns = convert(d, module=module, name=name if len(defs) == 1 else None, flags=flags if len(defs) == 1 else {**flags, "doctype_name": None})
        except MetaError as e:
            p.errors.append(str(e))
            continue
        p.warnings += warns
        if not DOCTYPE_NAME_RE.match(spec["name"]):
            p.errors.append(f"{spec['name']}: DocType names are letters, digits and spaces (at most 61 characters)")
            continue
        if not spec["module"]:
            p.errors.append(f"{spec['name']}: a module is required (in the JSON or the Module option)")
            continue
        if spec["name"] in seen_names:
            p.errors.append(f"{spec['name']}: defined twice in this JSON")
            continue
        seen_names.add(spec["name"])
        if not spec["fields"]:
            p.errors.append(f"{spec['name']}: at least one field is required")
            continue
        try:
            parsed[spec["name"]] = DocType.from_dict(spec, app=app, source="(creator)")
        except MetaError as e:
            p.errors.extend(f"{spec['name']}: {x}" for x in (getattr(e, "details", None) or [str(e)]))
            continue
        p.specs.append(spec)
    # 2. conflicts with what already exists
    existing = {d.name: d for d in registry.all()} if _registry_ready() else {}
    for spec in list(p.specs):
        target = _target(base, app, spec)
        if spec["name"] in existing or target.exists():
            msg = f"{spec['name']} already exists" + (f" ({target})" if target.exists() else "")
            if on_conflict == "skip":
                p.skipped.append(spec["name"])
                p.specs.remove(spec)
            else:
                p.conflicts.append(msg)
                p.errors.append(msg + ". Choose 'skip existing' to leave it alone, or rename it.")
    # 3. cross-validation over (what exists) + (what is new): link targets, child tables, reserved names
    new = {n: d for n, d in parsed.items() if n not in p.skipped}
    mine = tuple(f"{n}." for n in new)
    p.errors += [e for e in cross_check({**existing, **new}) if e.startswith(mine)]          # problems in DocTypes that already existed are not ours to report
    # 4. dependency order (child tables first) and target paths
    p.specs.sort(key=lambda s: (not s.get("istable"), s["name"]))
    p.writes = [(s["name"], _target(base, app, s)) for s in p.specs]
    return p


def _registry_ready() -> bool:
    try:
        registry.all()
        return True
    except Exception:  # noqa: BLE001 - no site loaded (plain CLI): only file conflicts are checked
        return False


# ---- create: all or nothing ------------------------------------------------------------------------------------------------------
def create(p: Plan) -> dict:
    if p.errors:
        raise MetaError("Nothing was created:\n  - " + "\n  - ".join(p.errors), details=p.errors)
    if not p.specs:
        return {"created": [], "files": [], "skipped": p.skipped, "warnings": p.warnings}
    made: list[Path] = []                      # every directory we create, so a failure can undo exactly that
    files: list[str] = []
    try:
        for spec in p.specs:
            d = dict(p.writes)[spec["name"]]
            folder = d.name
            for parent in (d.parent.parent, d.parent):                          # <module>/ and <module>/doctype/ need __init__.py
                if not parent.exists():
                    parent.mkdir(parents=True)
                    made.append(parent)
                (parent / "__init__.py").touch()
            d.mkdir()
            made.append(d)
            (d / "__init__.py").write_text("")
            (d / f"{folder}.json").write_text(json.dumps(spec, indent=2) + "\n")
            files += [str(d / "__init__.py"), str(d / f"{folder}.json")]
            if not spec.get("istable"):
                (d / f"{folder}.py").write_text(f'from velora import Document\n\n\nclass {pascal(spec["name"])}(Document):\n    def validate(self):\n        pass\n')
                files.append(str(d / f"{folder}.py"))
                # blank client-side files, like Frappe: the form script and the list-view settings, ready to edit in the File Explorer
                (d / f"{folder}.js").write_text(f'velora.ui.form.on("{spec["name"]}", {{\n  refresh(frm) {{}},\n}});\n')
                (d / f"{folder}_list.js").write_text(f'velora.listview_settings["{spec["name"]}"] = {{\n  add_fields: [],\n}};\n')
                files += [str(d / f"{folder}.js"), str(d / f"{folder}_list.js")]
    except Exception:
        for d in reversed(made):
            shutil.rmtree(d, ignore_errors=True)
        raise
    return {"created": [s["name"] for s in p.specs], "files": files, "skipped": p.skipped, "warnings": p.warnings}
