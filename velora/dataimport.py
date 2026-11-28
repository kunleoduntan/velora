"""Data Import and Export for ANY DocType - the Frappe-style way to load and migrate data.

  Import   Excel (.xlsx), CSV or JSON  ->  documents. Columns are matched by LABEL or FIELDNAME in any order; child-table columns are headed `Table.Field`
           (e.g. `Items.Description`) and a document's extra child rows go on the lines UNDER it, with the parent cells left blank. Modes: insert, update, upsert.
           A DRY RUN runs the real validation (links, required fields, unique values, your controllers' rules) and then rolls everything back, so what it
           reports is exactly what the real import would do. Every document is its own unit: one bad row never stops or half-applies the others (unless you ask for
           all-or-nothing). Failed rows come back with the reason, ready to fix and re-upload.
  Export   the same DocType -> JSON, CSV or Excel in exactly the layout the import reads, so data round-trips between companies and servers.

Imports go through the normal Document engine as the signed-in user, so permissions, validation, naming series, hooks, version history and notifications all apply.
"""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import xlsxwriter
from sqlalchemy import func, insert, select

from . import db
from .db.system import export_log
from .db.tables import get_table
from .document.document import get_doc, get_list, new_doc, now
from .exceptions import PermissionDenied, ValidationError
from .meta.registry import registry
from .permissions import check_permission, get_session

MAX_FILE_BYTES = 10 * 1024 * 1024
API_MAX_ROWS = 2000
MAX_ROWS = 200_000
EXPORT_MAX_ROWS = 50_000
MODES = ("insert", "update", "upsert")
DATE_FORMATS = ("DMY", "MDY", "YMD")
TRUE = {"1", "true", "yes", "y", "x", "checked", "on", "t"}
FALSE = {"0", "false", "no", "n", "off", "unchecked", "f"}
CURRENCY = "₦$€£¥ "


class ImportFileError(ValidationError):
    """The file itself cannot be used (wrong type, too big, no header ...)."""


@dataclass
class Options:
    mode: str = "insert"
    submit: bool = False
    dry_run: bool = False
    atomic: bool = False             # all or nothing: if any document fails, NOTHING is imported
    keep_names: bool = False         # insert with the ID from the file (for migration); needs System Manager
    date_format: str = "DMY"
    match: str | None = None         # update/upsert: find existing documents by this unique field instead of the ID
    max_rows: int = MAX_ROWS


@dataclass
class Group:
    row: int                                                   # the line in the file where this document starts (1 = the header)
    values: dict = field(default_factory=dict)                 # fieldname -> raw
    children: dict = field(default_factory=dict)               # table fieldname -> [ {child fieldname -> raw}, ... ]
    child_rows: dict = field(default_factory=dict)             # table fieldname -> [file line of each child row]
    source: list = field(default_factory=list)                 # the original file rows (for the error file)


# ------------------------------------------------------------------------------ columns ----------------------------------------------------------------------
def _label(f) -> str:
    """The name a person sees for a field (the same rule the Desk uses)."""
    return f.label or f.fieldname.replace("_", " ").title()


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _key(s) -> str:
    return re.sub(r"[^a-z0-9.]", "", str(s or "").lower().replace("*", ""))


def importable(meta) -> list:
    """Fields a person can supply: real columns that are not computed (read-only) and not layout."""
    return [f for f in meta.fields if f.has_column and not f.read_only and not f.is_layout]


def _child_meta(f):
    return registry.get(f.options) if registry.exists(f.options) else None


def column_specs(meta) -> list[dict]:
    """Every column the importer understands: [{header, kind: id|field|child, field, table, type, required, options, link}]."""
    cols = [{"header": "ID", "kind": "id", "field": "name", "type": "Data", "required": False, "options": None, "link": None, "note": "Leave blank to create; fill in to update an existing document"}]
    for f in importable(meta):
        cols.append(_spec(f, None))
    for t in meta.table_fields:
        cm = _child_meta(t)
        if cm is None:
            continue
        for cf in importable(cm):
            cols.append({**_spec(cf, t), "header": f"{_label(t)}.{_label(cf)}"})
    return cols


def _spec(f, table) -> dict:
    return {"header": _label(f), "kind": "child" if table else "field", "field": f.fieldname, "table": table.fieldname if table else None, "type": f.fieldtype,
            "required": bool(f.required), "options": list(f.choices) if f.fieldtype == "Select" else None, "link": f.options if f.fieldtype == "Link" else None, "note": f.description or ""}


def map_headers(meta, headers: list[str]) -> tuple[dict, list[str]]:
    """{column index: spec}, and the headers that matched nothing."""
    by_key: dict[str, dict] = {}
    for s in column_specs(meta):
        by_key.setdefault(_key(s["header"]), s)
        if s["kind"] == "field":
            by_key.setdefault(_key(s["field"]), s)
        elif s["kind"] == "child":
            by_key.setdefault(_key(f"{s['table']}.{s['field']}"), s)
            t = meta.get_field(s["table"])
            by_key.setdefault(_key(f"{_label(t)}.{s['field']}"), s)
            by_key.setdefault(_key(f"{s['table']}.{s['header'].split('.', 1)[1]}"), s)
    by_key["id"] = by_key["name"] = by_key[_key("ID")]
    mapping, unknown = {}, []
    for i, h in enumerate(headers):
        if h in (None, ""):
            continue
        spec = by_key.get(_key(h))
        if spec is None:
            unknown.append(str(h))
        else:
            mapping[i] = spec
    return mapping, unknown


# ------------------------------------------------------------------------------ reading files ---------------------------------------------------------------
def read_table(data: bytes, filename: str) -> tuple[list[str], list[list]] | list[dict]:
    """(headers, rows) for Excel/CSV, or a list of nested objects for JSON. Raises ImportFileError with a plain reason."""
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError(f"The file is {len(data) // 1024 // 1024} MB; the limit is {MAX_FILE_BYTES // 1024 // 1024} MB. Split it, or use `velora import-data` on the server.")
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(data)
    if name.endswith((".csv", ".txt", ".tsv")):
        return _read_csv(data)
    if name.endswith(".json"):
        return _read_json(data)
    raise ImportFileError("Unsupported file type. Use an Excel file (.xlsx), a CSV file (.csv) or a JSON file (.json).")


def _read_csv(data: bytes):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")                 # Excel's "CSV" on Windows
    first = text.split("\n", 1)[0]
    delim = max((",", ";", "\t"), key=lambda d: first.count(d)) if first else ","
    rows = [[c for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]
    return _split_header(rows)


def _read_xlsx(data: bytes):
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - corrupt, password protected, not really xlsx
        raise ImportFileError("That is not a readable Excel (.xlsx) file. Is it password-protected or damaged? You can also save it as CSV.") from e
    ws = wb[wb.sheetnames[0]]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return _split_header(rows)


def _read_json(data: bytes):
    try:
        obj = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ImportFileError(f"That is not valid JSON: {e}") from None
    if isinstance(obj, dict):
        obj = next((obj[k] for k in ("data", "docs", "records", "items") if isinstance(obj.get(k), list)), None)
    if not isinstance(obj, list) or not all(isinstance(x, dict) for x in obj):
        raise ImportFileError("JSON must be a list of objects, one per document (optionally inside {\"data\": [...]}).")
    return obj


def _split_header(rows: list[list]):
    rows = [r for r in rows if any(c not in (None, "") for c in r)] if rows else []
    if not rows:
        raise ImportFileError("The file is empty: it needs a header row and at least one data row.")
    headers = [str(c).strip() if c is not None else "" for c in rows[0]]
    seen: dict[str, int] = {}
    for h in headers:
        if h and _key(h) in seen:
            raise ImportFileError(f"The column {h!r} appears twice in the header row. Each column may appear once.")
        if h:
            seen[_key(h)] = 1
    return headers, rows[1:]


def build_groups(meta, parsed) -> tuple[list[Group], list[str], list[dict]]:
    """(documents, unknown headers, problems). Problems are file-level mistakes such as a first row that is only child cells."""
    if isinstance(parsed, list):                                            # JSON
        groups = []
        for i, obj in enumerate(parsed, 1):
            g = Group(row=i, source=[obj])
            for k, v in obj.items():
                if k in ("doctype", "docstatus", "creation", "modified", "owner", "modified_by", "idx"):
                    continue
                f = meta.get_field(k)
                if f is not None and f.is_table:
                    g.children[k] = [{ck: cv for ck, cv in r.items() if not _blank(cv)} for r in (v or []) if isinstance(r, dict)]
                    g.child_rows[k] = [i] * len(g.children[k])
                elif not _blank(v):
                    g.values[k] = v                                         # null / "" = blank, exactly like an empty cell: never imported, never erases
            groups.append(g)
        return groups, [], []
    headers, rows = parsed
    mapping, unknown = map_headers(meta, headers)
    if not mapping:
        raise ImportFileError(f"None of the column headings in the file match {meta.name}. Download the template to see the headings it understands.")
    groups, problems = [], []
    for n, raw in enumerate(rows, 2):
        parent, child = {}, {}
        for i, spec in mapping.items():
            v = raw[i] if i < len(raw) else None
            if v in (None, "") or (isinstance(v, str) and not v.strip()):
                continue
            if spec["kind"] == "child":
                child.setdefault(spec["table"], {})[spec["field"]] = v
            else:
                parent[spec["field"]] = v
        if parent:
            groups.append(Group(row=n, values=parent, source=[dict(zip(headers, raw))]))
        elif not child:
            continue                                                        # a blank line
        elif not groups:
            problems.append({"row": n, "field": "", "message": "This line has only child-table cells, but no document has started yet. The first line of each document must have its own fields filled in."})
            continue
        else:
            groups[-1].source.append(dict(zip(headers, raw)))
        g = groups[-1]
        for t, vals in child.items():
            g.children.setdefault(t, []).append(vals)
            g.child_rows.setdefault(t, []).append(n)
    return groups, unknown, problems


# ------------------------------------------------------------------------------ values -------------------------------------------------------------------------
class _Bad(Exception):
    pass


def _s(v) -> str:
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _number(v) -> Decimal:
    if isinstance(v, bool):
        raise _Bad(f"{v!r} is not a number")
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    t = _s(v)
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "").strip(CURRENCY).strip()
    if t.endswith("-"):
        neg, t = True, t[:-1]
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise _Bad(f"{_s(v)!r} is not a number") from None
    if not d.is_finite():
        raise _Bad(f"{_s(v)!r} is not a number")
    return -d if neg else d


def parse_date(v, fmt: str = "DMY") -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):                         # an Excel serial date
        if 10000 <= v < 80000:                                                          # years 1927-2118: a small number in a date column is a mistake, not 1900
            return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
        raise _Bad(f"{v} is not a date")
    t = _s(v)
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?", t)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?:[ T].*)?", t)
        if m:
            a, b, y = map(int, m.groups())
            mo, d = (a, b) if fmt == "MDY" else (b, a)
        else:
            for pat in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d-%B-%Y"):
                try:
                    return datetime.strptime(t, pat).date()
                except ValueError:
                    pass
            raise _Bad(f"{t!r} is not a date (use YYYY-MM-DD" + (" or DD/MM/YYYY" if fmt != "MDY" else " or MM/DD/YYYY") + ")")
    try:
        return date(y, mo, d)
    except ValueError:
        raise _Bad(f"{t!r} is not a real date") from None


def parse_datetime(v, fmt: str = "DMY") -> datetime:
    if isinstance(v, datetime):
        return v
    t = _s(v)
    m = re.search(r"[ T](\d{1,2}):(\d{2})(?::(\d{2}))?", t)
    d = parse_date(v if not isinstance(v, str) else (t[:m.start()] if m else t), fmt)
    return datetime(d.year, d.month, d.day, int(m.group(1)) if m else 0, int(m.group(2)) if m else 0, int(m.group(3) or 0) if m else 0)


@dataclass
class Ctx:
    opts: Options
    links: dict = field(default_factory=dict)

    def link(self, target: str, value: str) -> str:
        """The name of the document `value` refers to (by ID, then ignoring case, then by its title). Raises _Bad with a hint."""
        key = (target, value)
        if key in self.links:
            return self.links[key]
        if not registry.exists(target):
            self.links[key] = value
            return value
        tm, t = registry.get(target), get_table(target)
        with db.transaction() as c:
            hit = c.execute(select(t.c.name).where(t.c.name == value)).scalar()
            if hit is None:
                near = c.execute(select(t.c.name).where(func.lower(t.c.name) == value.lower()).limit(2)).scalars().all()
                if len(near) == 1:
                    hit = near[0]
            if hit is None and tm.title_field and tm.title_field in t.c:
                near = c.execute(select(t.c.name).where(t.c[tm.title_field] == value).limit(2)).scalars().all()
                if len(near) == 1:
                    hit = near[0]
                elif len(near) > 1:
                    raise _Bad(f"{value!r} matches more than one {target} by name; use the ID instead")
        if hit is None:
            raise _Bad(f"{value!r} is not an existing {target}. Create it first, or fix the spelling")
        self.links[key] = hit
        return hit


def parse_value(f, raw, ctx: Ctx):
    """One cell -> the value for the field. Raises _Bad('...') with a plain reason."""
    t = f.fieldtype
    if _blank(raw):
        return None
    if t in ("Data", "Text"):
        s = _s(raw) if not isinstance(raw, str) else raw.strip()
        if s.startswith("'="):
            s = s[1:]                                                       # our CSV export protects text that starts with "="
        if t == "Data" and len(s) > (f.length or 255):
            raise _Bad(f"too long: {len(s)} characters, at most {f.length or 255} allowed")
        return s
    if t == "Int":
        d = _number(raw)
        if d != d.to_integral_value():
            raise _Bad(f"{_s(raw)!r} is not a whole number")
        return int(d)
    if t == "Float":
        return float(_number(raw))
    if t == "Currency":
        return _number(raw)
    if t == "Check":
        if isinstance(raw, bool):
            return int(raw)
        s = _s(raw).lower()
        if s in TRUE:
            return 1
        if s in FALSE or s == "":
            return 0
        raise _Bad(f"{_s(raw)!r} is not yes/no (use 1, 0, yes, no, true or false)")
    if t == "Date":
        return parse_date(raw, ctx.opts.date_format)
    if t == "Datetime":
        return parse_datetime(raw, ctx.opts.date_format)
    if t == "Select":
        s = _s(raw)
        match = next((o for o in f.choices if _key(o) == _key(s)), None)
        if match is None:
            raise _Bad(f"{s!r} is not one of: {', '.join(f.choices)}")
        return match
    if t == "Link":
        return ctx.link(f.options, _s(raw))
    if t == "JSON":
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(_s(raw))
        except ValueError:
            raise _Bad("not valid JSON") from None
    return raw if not isinstance(raw, str) else raw.strip()


# ------------------------------------------------------------------------------ running ------------------------------------------------------------------------
@dataclass
class Report:
    doctype: str
    mode: str
    dry_run: bool
    total: int = 0
    created: int = 0
    updated: int = 0
    failed: int = 0
    unknown_columns: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    names: list = field(default_factory=list)
    failed_rows: list = field(default_factory=list)
    rolled_back: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {"doctype": self.doctype, "mode": self.mode, "dry_run": self.dry_run, "total": self.total, "created": self.created, "updated": self.updated, "failed": self.failed,
                "ok": self.failed == 0, "unknown_columns": self.unknown_columns, "errors": self.errors[:500], "errors_truncated": len(self.errors) > 500, "names": self.names[:200],
                "failed_rows": self.failed_rows[:1000], "rolled_back": self.rolled_back, "duration_ms": self.duration_ms}


class _Abort(Exception):
    pass


def _build(meta, g: Group, ctx: Ctx, errors: list) -> dict | None:
    """Parse one document's cells. Every bad cell is reported (with its line and column); returns None if any was bad."""
    out: dict = {}
    bad = False
    fields = {f.fieldname: f for f in importable(meta)}
    for k, raw in g.values.items():
        if k == "name":
            out["name"] = _s(raw)
            continue
        f = fields.get(k)
        if f is None:
            if meta.get_field(k) is None:
                errors.append({"row": g.row, "field": k, "message": f"{meta.name} has no field {k!r}"})
            else:
                errors.append({"row": g.row, "field": k, "message": "this column is calculated or read-only, so it cannot be imported"})
            bad = True
            continue
        try:
            out[k] = parse_value(f, raw, ctx)
        except _Bad as e:
            errors.append({"row": g.row, "field": _label(f), "message": str(e)})
            bad = True
    for t, rows in g.children.items():
        tf = meta.get_field(t)
        cm = _child_meta(tf) if tf is not None else None
        if cm is None:
            errors.append({"row": g.row, "field": t, "message": f"{meta.name} has no table {t!r}"})
            bad = True
            continue
        cfields = {f.fieldname: f for f in importable(cm)}
        built = []
        for i, row in enumerate(rows):
            line = g.child_rows[t][i] if i < len(g.child_rows.get(t, [])) else g.row
            item = {}
            for k, raw in row.items():
                f = cfields.get(k)
                if f is None:
                    errors.append({"row": line, "field": f"{_label(tf)}.{k}", "message": "this column cannot be imported"})
                    bad = True
                    continue
                try:
                    item[k] = parse_value(f, raw, ctx)
                except _Bad as e:
                    errors.append({"row": line, "field": f"{_label(tf)}.{_label(f)}", "message": str(e)})
                    bad = True
            built.append(item)
        out[t] = built
    return None if bad else out


def _find_existing(meta, values: dict, opts: Options) -> str | None:
    name = values.pop("name", None)
    if opts.match:
        v = values.get(opts.match)
        if v in (None, ""):
            return None
        t = get_table(meta.name)
        with db.transaction() as c:
            return c.execute(select(t.c.name).where(t.c[opts.match] == v)).scalar()
    if name:
        t = get_table(meta.name)
        with db.transaction() as c:
            return name if c.execute(select(t.c.name).where(t.c.name == name)).first() else None
    return None


def _apply(meta, g: Group, values: dict, opts: Options) -> tuple[str, str]:
    given_name = values.get("name")
    existing = _find_existing(meta, values, opts) if opts.mode in ("update", "upsert") else None
    if opts.mode == "update" and existing is None:
        raise ValidationError(f"There is no {meta.name} to update" + (f" with ID {given_name!r}" if given_name else ": give the ID column (or use --match with a unique field)"))
    if existing is not None:
        doc = get_doc(meta.name, existing)
        if doc.docstatus != 0:
            raise ValidationError(f"{existing} is {'submitted' if doc.docstatus == 1 else 'cancelled'} and can no longer be changed")
        doc.update(values)                                         # blank cells never reach here, so they can never erase
        doc.save()
        return "updated", doc.name
    values.pop("name", None)
    doc = new_doc(meta.name, **values)
    if given_name and (opts.keep_names or meta.autoname == "prompt"):
        doc.name = given_name                                              # migration: keep the original ID (otherwise the naming series decides)
    doc.insert()
    if opts.submit and meta.is_submittable:
        doc.submit()
    return "created", doc.name


def run(doctype: str, groups: list[Group], opts: Options, unknown: list[str] | None = None, problems: list[dict] | None = None) -> Report:
    meta = registry.get(doctype)
    if meta.istable:
        raise ValidationError(f"{doctype} is a child table: import the parent document with its rows instead")
    if opts.mode not in MODES:
        raise ValidationError(f"mode must be one of: {', '.join(MODES)}")
    if opts.date_format not in DATE_FORMATS:
        raise ValidationError(f"date format must be one of: {', '.join(DATE_FORMATS)}")
    if len(groups) > opts.max_rows:
        raise ImportFileError(f"The file has {len(groups)} documents; at most {opts.max_rows} can be imported in one go here. Split it, or use `velora import-data` on the server.")
    if opts.mode in ("insert", "upsert"):
        check_permission(meta, "create")
    # Import is an explicit permission when at least one role on the DocType declares it.
    # Older DocTypes without an import column retain the existing create/write behavior.
    if any(getattr(p, "import_", False) for p in meta.permissions):
        check_permission(meta, "import")
    if opts.mode in ("update", "upsert"):
        check_permission(meta, "write")
    if opts.submit:
        if not meta.is_submittable:
            raise ValidationError(f"{doctype} cannot be submitted, so 'submit' does not apply")
        check_permission(meta, "submit")
    if opts.match:
        mf = meta.get_field(opts.match)
        if opts.match != "name" and (mf is None or not mf.unique):
            raise ValidationError(f"--match must be a unique field of {meta.name} (or name)")
    if opts.keep_names:
        s = get_session()
        if not (s.user == "Administrator" or "System Manager" in s.roles):
            raise PermissionDenied("Only a System Manager may import with the IDs from the file (keep names)")
    started = datetime.now()
    rep = Report(doctype=doctype, mode=opts.mode, dry_run=opts.dry_run, total=len(groups), unknown_columns=list(unknown or []), errors=list(problems or []))
    ctx = Ctx(opts)
    from .permissions import memoized
    try:
        with db.transaction(), memoized():                  # roles, workflows and scripts cannot change mid-import: read them once, not per row
            for g in groups:
                errs: list = []
                values = _build(meta, g, ctx, errs)
                try:
                    if values is None:
                        raise _Cells(errs)
                    with db.conn().begin_nested():                         # a savepoint: this document succeeds or leaves no trace
                        action, name = _apply(meta, g, values, opts)
                except _Cells as e:
                    _fail(rep, g, e.errors)
                    if opts.atomic:
                        raise _Abort() from None
                    continue
                except Exception as e:  # noqa: BLE001 - the Document engine's reason (validation, permission, duplicate ...) is the message
                    _fail(rep, g, [{"row": g.row, "field": "", "message": _reason(e)}])
                    if opts.atomic:
                        raise _Abort() from None
                    continue
                rep.created += action == "created"
                rep.updated += action == "updated"
                rep.names.append(name)
            if opts.dry_run:
                raise _Abort()                                              # (all-or-nothing aborts at the first failure, above)
    except _Abort:
        rep.rolled_back = True
        if opts.atomic and rep.failed and not opts.dry_run:
            rep.created = rep.updated = 0
    rep.duration_ms = int((datetime.now() - started).total_seconds() * 1000)
    return rep


class _Cells(Exception):
    def __init__(self, errors):
        self.errors = errors


def _reason(e: Exception) -> str:
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return msg


def _fail(rep: Report, g: Group, errors: list) -> None:
    rep.failed += 1
    rep.errors.extend(errors)
    reason = "; ".join(f"{e['field'] + ': ' if e['field'] else ''}{e['message']}" for e in errors)[:500]
    for i, src in enumerate(g.source):
        rep.failed_rows.append({"row": g.row if i == 0 else g.row + i, "error": reason if i == 0 else "", "data": src})


def import_file(doctype: str, data: bytes, filename: str, opts: Options | None = None, log: bool = True) -> Report:
    """Read a file and import it. The one call the API and the command line make."""
    opts = opts or Options()
    meta = registry.get(doctype)
    parsed = read_table(data, filename)
    groups, unknown, problems = build_groups(meta, parsed)
    if not groups and not problems:
        raise ImportFileError("The file has a header row but no data rows.")
    rep = run(doctype, groups, opts, unknown, problems)
    if log and not opts.dry_run:
        _log(f"import-{opts.mode}", doctype, rep.created + rep.updated, {"file": filename, "created": rep.created, "updated": rep.updated, "failed": rep.failed, "atomic": opts.atomic})
    return rep


def errors_csv(rep: Report | dict) -> str:
    """The failed rows as a CSV (original columns + Error), ready to correct and import again."""
    rows = rep["failed_rows"] if isinstance(rep, dict) else rep.failed_rows
    cols = list(dict.fromkeys(k for r in rows for k in r["data"]))
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([*cols, "Error"])
    for r in rows:
        w.writerow([_cell(r["data"].get(c)) for c in cols] + [r["error"]])
    return out.getvalue()


# ------------------------------------------------------------------------------ template ---------------------------------------------------------------------
def template(doctype: str, fmt: str = "xlsx") -> tuple[bytes, str, str]:
    """(bytes, filename, content type): a file with the right headings, and (for Excel) an Instructions sheet."""
    meta = registry.get(doctype)
    check_permission(meta, "create")
    cols = column_specs(meta)
    heads = [c["header"] + (" *" if c["required"] else "") for c in cols]
    slug = re.sub(r"[^A-Za-z0-9]+", "_", doctype).strip("_")
    if fmt == "csv":
        out = io.StringIO()
        csv.writer(out).writerow(heads)
        return out.getvalue().encode("utf-8-sig"), f"{slug}_import_template.csv", "text/csv; charset=utf-8"
    if fmt != "xlsx":
        raise ValidationError("format must be xlsx or csv")
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    head, req, wrap = wb.add_format({"bold": True, "bg_color": "#E8EAF6", "border": 1}), wb.add_format({"bold": True, "bg_color": "#FFE0B2", "border": 1}), wb.add_format({"text_wrap": True, "valign": "top"})
    ws = wb.add_worksheet("Import")
    for i, c in enumerate(cols):
        ws.write_string(0, i, heads[i], req if c["required"] else head)
        ws.set_column(i, i, max(14, min(40, len(heads[i]) + 2)))
    ws.freeze_panes(1, 0)
    ins = wb.add_worksheet("Instructions")
    notes = [f"How to import {doctype}", "",
             "1. Fill in the Import sheet, one document per line. Orange headings are required. You may delete columns you do not need and reorder the rest.",
             "2. A document with several child rows (for example invoice lines): put the first row on the document's own line, and each further row on the lines UNDER it, "
             "leaving the document's own cells blank. Child columns are written Table.Field.",
             "3. ID: leave blank to create new documents. To change existing ones, fill in the ID and choose 'update' (or 'upsert'). Empty cells never erase existing data.",
             "4. Dates: YYYY-MM-DD (or DD/MM/YYYY). Yes/No columns: yes, no, 1, 0, true or false. Numbers may contain thousands commas.",
             "5. Links must name something that already exists. Press 'Check file' first: it runs the real validation and saves nothing.", ""]
    for i, n in enumerate(notes):
        ins.write_string(i, 0, n, wrap)
    r = len(notes)
    for j, h in enumerate(("Column", "Type", "Required", "Allowed values / links to", "Notes")):
        ins.write_string(r, j, h, head)
    for c in cols:
        r += 1
        for j, v in enumerate((c["header"], c["type"], "yes" if c["required"] else "", ", ".join(c["options"]) if c["options"] else (f"an existing {c['link']}" if c["link"] else ""), c["note"])):
            ins.write_string(r, j, str(v), wrap)
    ins.set_column(0, 0, 70)
    ins.set_column(1, 4, 24)
    wb.close()
    return buf.getvalue(), f"{slug}_import_template.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ------------------------------------------------------------------------------ export ------------------------------------------------------------------------
def _jsonable(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _cell(v):
    if v is None:
        return ""
    v = _jsonable(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, str) and v.startswith("="):
        return "'" + v                                                      # never let a text cell become a live formula in a spreadsheet
    return v


def _fetch(doctype: str, filters, limit: int, names=None) -> list[dict]:
    meta = registry.get(doctype)
    fields = ["name", "docstatus"] + [f.fieldname for f in meta.fields if f.has_column and not f.is_layout]
    flt = [list(f) for f in (filters or [])]
    if names:
        flt.append(["name", "in", list(names)])
    return get_list(doctype, filters=flt, fields=list(dict.fromkeys(fields)), order_by="creation asc", limit=limit)


def _children(meta, parents: list[dict]) -> dict:
    """{table fieldname: {parent name: [child row dicts]}}"""
    out: dict = {}
    names = [p["name"] for p in parents]
    for t in meta.table_fields:
        cm = _child_meta(t)
        if cm is None:
            continue
        ct = get_table(cm.name)
        cols = [f.fieldname for f in cm.fields if f.has_column and not f.is_layout]
        by: dict = {}
        with db.transaction() as c:
            for i in range(0, len(names), 500):
                q = select(ct.c.parent, *[ct.c[x] for x in cols]).where(ct.c.parent.in_(names[i:i + 500]), ct.c.parentfield == t.fieldname).order_by(ct.c.parent, ct.c.idx)
                for r in c.execute(q).mappings():
                    by.setdefault(r["parent"], []).append({k: r[k] for k in cols})
        out[t.fieldname] = by
    return out


def export_data(doctype: str, fmt: str = "json", filters=None, limit: int = EXPORT_MAX_ROWS, names=None) -> tuple[bytes, str, str, int]:
    """(bytes, filename, content type, document count). The layout is exactly what `import_file` reads."""
    meta = registry.get(doctype)
    check_permission(meta, "read")
    check_permission(meta, "export")
    if fmt not in ("json", "csv", "xlsx"):
        raise ValidationError("format must be json, csv or xlsx")
    limit = max(1, min(int(limit), EXPORT_MAX_ROWS))
    parents = _fetch(doctype, filters, limit, names)
    kids = _children(meta, parents)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", doctype).strip("_")
    stamp = now().strftime("%Y%m%d_%H%M")
    if fmt == "json":
        docs = []
        for p in parents:
            d = {"doctype": doctype, **{k: _jsonable(v) for k, v in p.items()}, "docstatus": p.get("docstatus")}
            for t in kids:
                d[t] = [{k: _jsonable(v) for k, v in r.items()} for r in kids[t].get(p["name"], [])]
            docs.append(d)
        body = json.dumps({"doctype": doctype, "exported": stamp, "count": len(docs), "data": docs}, ensure_ascii=False, indent=1).encode()
        _log("export-json", doctype, len(docs), {"filters": filters})
        return body, f"{slug}_{stamp}.json", "application/json", len(docs)
    cols = column_specs(meta)
    heads = [c["header"] for c in cols]
    lines: list[list] = []
    for p in parents:
        tables = {t: kids[t].get(p["name"], []) for t in kids}
        for k in range(max([1] + [len(v) for v in tables.values()])):
            row = []
            for c in cols:
                if c["kind"] == "child":
                    rows = tables.get(c["table"], [])
                    row.append(_cell(rows[k].get(c["field"])) if k < len(rows) else "")
                elif k == 0:
                    row.append(_cell(p.get(c["field"])))
                else:
                    row.append("")
            lines.append(row)
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(heads)
        w.writerows(lines)
        _log("export-csv", doctype, len(parents), {"filters": filters})
        return out.getvalue().encode("utf-8-sig"), f"{slug}_{stamp}.csv", "text/csv; charset=utf-8", len(parents)
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("Import")
    hf = wb.add_format({"bold": True, "bg_color": "#E8EAF6", "border": 1})
    for i, h in enumerate(heads):
        ws.write_string(0, i, h, hf)
        ws.set_column(i, i, max(14, min(40, len(h) + 2)))
    for r, line in enumerate(lines, 1):
        for i, v in enumerate(line):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                ws.write_number(r, i, v)
            elif v != "":
                ws.write_string(r, i, str(v))                               # always text: a cell can never become a formula
    ws.freeze_panes(1, 0)
    wb.close()
    _log("export-xlsx", doctype, len(parents), {"filters": filters})
    return buf.getvalue(), f"{slug}_{stamp}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", len(parents)


def _log(scope: str, doctype: str, n: int, detail: dict) -> None:
    try:
        with db.transaction() as conn:
            conn.execute(insert(export_log).values(name=secrets.token_hex(8), ref_doctype=doctype, owner=get_session().user, creation=now(), scope=scope[:20], row_count=n, detail=detail))
    except Exception:  # noqa: BLE001 - the audit line must never be the reason an import fails after it already succeeded
        pass


# ------------------------------------------------------------------------------ grids (a child table inside a form) --------------------------------------
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def grid_columns(child_doctype: str) -> list:
    """The columns of a child-table grid that a person can fill in (computed ones are left out)."""
    if not registry.exists(child_doctype):
        raise ValidationError(f"Unknown table {child_doctype!r}")
    cm = registry.get(child_doctype)
    if not cm.istable:
        raise ValidationError(f"{child_doctype} is not a child table")
    return importable(cm)


def _write_sheet(wb, name: str, heads: list[str], required: list[bool], lines: list[list]) -> None:
    ws = wb.add_worksheet(name)
    head, req = wb.add_format({"bold": True, "bg_color": "#E8EAF6", "border": 1}), wb.add_format({"bold": True, "bg_color": "#FFE0B2", "border": 1})
    for i, h in enumerate(heads):
        ws.write_string(0, i, h, req if required[i] else head)
        ws.set_column(i, i, max(14, min(40, len(h) + 2)))
    for r, line in enumerate(lines, 1):
        for i, v in enumerate(line):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                ws.write_number(r, i, v)
            elif v not in ("", None):
                ws.write_string(r, i, str(v))                               # always text: a cell can never become a formula
    ws.freeze_panes(1, 0)


def grid_export(child_doctype: str, rows: list[dict] | None = None) -> tuple[bytes, str, str]:
    """An Excel file of the rows currently in a grid (or just the headings when there are none): the same file `grid_parse` reads back."""
    cols = grid_columns(child_doctype)
    heads = [_label(f) + (" *" if f.required else "") for f in cols]
    lines = [[_cell(r.get(f.fieldname)) for f in cols] for r in (rows or []) if isinstance(r, dict)]
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    _write_sheet(wb, "Rows", heads, [bool(f.required) for f in cols], lines)
    wb.close()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", child_doctype).strip("_")
    return buf.getvalue(), f"{slug}_{'rows' if rows else 'template'}.xlsx", _XLSX


def grid_parse(child_doctype: str, data: bytes, filename: str, date_format: str = "DMY") -> dict:
    """Read an Excel file into grid rows. Every cell goes through the same checks as a normal import; nothing is saved.
    Returns {"rows": [...], "errors": [{"row": n, "column": label, "error": text}], "unknown": [headings that matched nothing]}."""
    if not (filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise ImportFileError("Upload an Excel file (.xlsx).")
    cols = grid_columns(child_doctype)
    headers, body = _read_xlsx(data) if len(data) <= MAX_FILE_BYTES else read_table(data, filename)
    by_key: dict[str, object] = {}
    for f in cols:
        by_key.setdefault(_key(_label(f)), f)
        by_key.setdefault(_key(f.fieldname), f)
    mapping, unknown = {}, []
    for i, h in enumerate(headers):
        if not h:
            continue
        f = by_key.get(_key(h.rstrip("*").strip()))
        if f is None:
            unknown.append(h)
        else:
            mapping[i] = f
    ctx = Ctx(Options(date_format=date_format.upper()))
    rows, errors = [], []
    for n, raw in enumerate(body, 2):
        row, bad = {}, False
        for i, f in mapping.items():
            cell = raw[i] if i < len(raw) else None
            try:
                v = parse_value(f, cell, ctx)
            except _Bad as e:
                errors.append({"row": n, "column": _label(f), "error": str(e)})
                bad = True
                continue
            if v is not None:
                row[f.fieldname] = v
        if not bad:
            rows.append({k: _jsonable(v) for k, v in row.items()})
    if len(rows) + len(errors) > API_MAX_ROWS:
        raise ImportFileError(f"At most {API_MAX_ROWS} rows can be loaded at once.")
    return {"rows": rows, "errors": errors, "unknown": unknown}


def errors_xlsx(rep: Report | dict) -> bytes:
    """The failed rows as an Excel file (original columns + Error), ready to correct and import again."""
    rows = rep["failed_rows"] if isinstance(rep, dict) else rep.failed_rows
    cols = list(dict.fromkeys(k for r in rows for k in r["data"]))
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    lines = [[_cell(r["data"].get(c)) for c in cols] + [r["error"]] for r in rows]
    _write_sheet(wb, "Import", [*cols, "Error"], [False] * (len(cols) + 1), lines)
    wb.close()
    return buf.getvalue()
