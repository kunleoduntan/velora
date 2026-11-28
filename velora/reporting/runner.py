"""Run a report: validate filters, check access, execute, stamp the result."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .. import site as site_mod
from ..company import current_company
from ..exceptions import DoesNotExistError, PermissionDenied, ValidationError
from ..meta.registry import registry
from ..permissions import check_permission, get_session, has_permission
from .definition import ReportDef, ReportFilter
from .model import ReportBuilder, ReportResult


def _today() -> date:
    return datetime.now(timezone.utc).date()


def resolve_default(token):
    t = _today()
    return {"Today": t, "Month Start": t.replace(day=1), "Year Start": t.replace(month=1, day=1), "Year End": t.replace(month=12, day=31),
            "Month End": (t.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1),
            "Quarter Start": t.replace(month=3 * ((t.month - 1) // 3) + 1, day=1)}.get(token, token)


def check_report_access(rdef: ReportDef) -> None:
    s = get_session()
    if s.user != "Administrator":
        if rdef.roles and not (set(rdef.roles) & set(s.roles)):
            raise PermissionDenied(f"{s.user} may not run the report {rdef.name!r}")
    if rdef.ref_doctype:
        check_permission(registry.get(rdef.ref_doctype), "read")


def can_run(rdef: ReportDef) -> bool:
    try:
        check_report_access(rdef)
        return True
    except (PermissionDenied, DoesNotExistError):
        return False


def can_export(rdef: ReportDef) -> bool:
    return can_run(rdef) and (not rdef.ref_doctype or has_permission(registry.get(rdef.ref_doctype), "export"))


def normalize_filters(rdef: ReportDef, given: dict | None) -> dict:
    given = dict(given or {})
    known = {f.fieldname: f for f in rdef.filters}
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise ValidationError(f"Report {rdef.name}: unknown filter(s) {unknown}")
    out = {}
    for name, f in known.items():
        v = given.get(name)
        if v in (None, ""):
            v = resolve_default(f.default) if f.default not in (None, "") else None
        if v in (None, ""):
            if f.required:
                raise ValidationError(f"Filter '{f.label}' is required")
            continue
        try:
            if f.fieldtype == "Date":
                v = v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])
            elif f.fieldtype == "Check":
                v = str(v).lower() not in ("0", "false", "no", "")
            elif f.fieldtype == "Int":
                v = int(v)
            elif f.fieldtype in ("Float", "Currency"):
                v = float(v)
            elif f.fieldtype == "Any":
                pass                                  # ad-hoc filters: lists for in/between etc. are validated + coerced by the query engine
            elif f.fieldtype == "Select":
                if str(v) not in f.options:
                    raise ValidationError(f"Filter '{f.label}' must be one of {f.options}")
                v = str(v)
            else:
                v = str(v)
        except (ValueError, TypeError):
            raise ValidationError(f"Filter '{f.label}': {v!r} is not a valid {f.fieldtype}") from None
        out[name] = v
    return out


def _fmt(v):
    return f"{v.day} {v:%b %Y}" if isinstance(v, (date, datetime)) else ("Yes" if v is True else "No" if v is False else str(v))


_WORDS = {"=": "is", "!=": "is not", ">": "is over", "<": "is under", ">=": "is at least", "<=": "is at most", "like": "contains",
          "not like": "does not contain", "in": "is one of", "not in": "is none of", "between": "is between"}


def _phrase(label: str, op: str, val) -> str:
    """Ad-hoc filters read as plain language: 'Status is not Inactive', 'Credit Limit is at least 1000'."""
    op = op.lower()
    if op == "is":
        return f"{label} is {'not set' if str(val).lower().replace(' ', '') == 'notset' else 'set'}"
    if isinstance(val, (list, tuple)):
        val = " and ".join(str(v) for v in val) if op == "between" else ", ".join(str(v) for v in val)
    return f"{label} {_WORDS.get(op, op)} {str(val).strip('%') if op in ('like', 'not like') else _fmt(val)}"


def _company_name() -> str:
    co = current_company()
    if co:
        return co.name
    from ..settings import get_setting
    brand = (get_setting("theme", {}) or {}).get("brand_name", "")
    name = site_mod.current().name
    return brand or ("" if name == "default" else name)


def run_definition(rdef: ReportDef, filters: dict | None) -> ReportResult:
    f = normalize_filters(rdef, filters)
    if rdef.type == "summary":
        from .summary import run_summary
        out = run_summary(rdef, f)
    else:
        out = registry.report_fn(rdef.name)(f)
    result = out.build() if isinstance(out, ReportBuilder) else out
    if not isinstance(result, ReportResult):
        raise ValidationError(f"Report {rdef.name}: execute() must return a ReportResult or ReportBuilder")
    labels = {x.fieldname: x.label for x in rdef.filters}
    if rdef.source == "ad-hoc":
        ops = {x.fieldname: x.op for x in rdef.filters}
        result.filters = result.filters or [(_phrase(labels[k], ops[k], v), "") for k, v in f.items()]
    else:
        result.filters = result.filters or [(labels[k], _fmt(v)) for k, v in f.items()]
    if not result.subtitle:
        lo, hi = f.get("from_date"), f.get("to_date")
        result.subtitle = (f"{_fmt(lo)} to {_fmt(hi)}" if lo and hi else f"From {_fmt(lo)}" if lo else f"As of {_fmt(hi)}" if hi else f"As of {_fmt(_today())}")
        result.filters = [x for x in result.filters if x[0] not in ("From Date", "To Date")]
    result.title = result.title or rdef.name
    result.report_name = rdef.name
    result.company = result.company or _company_name()
    result.generated_at = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    return result


def run_report(name: str, filters: dict | None = None) -> ReportResult:
    rdef = registry.report(name)
    check_report_access(rdef)
    return run_definition(rdef, filters)


def adhoc_definition(spec: dict) -> ReportDef:
    """Ad-hoc grouped report on any DocType (no registration needed): the framework's built-in report builder."""
    try:
        return ReportDef.from_dict({"name": str(spec.get("title") or f"{spec.get('doctype')} summary"), "type": "summary",
                                    "ref_doctype": spec.get("doctype", ""), "group_by": spec.get("group_by") or [],
                                    "measures": spec.get("measures") or [{"fn": "count", "label": "Count"}],
                                    "date_field": spec.get("date_field"), "date_bucket": spec.get("date_bucket"), "rollup": spec.get("rollup"), "gap_fill": spec.get("gap_fill"),
                                    "filters": spec.get("filter_defs") or []}, source="ad-hoc")
    except Exception as e:  # noqa: BLE001 - surface definition mistakes as validation errors, not 500s
        raise ValidationError(str(e).splitlines()[-1].strip("- ").strip()) from None


SPEC_KEYS = {"doctype", "group_by", "date_field", "date_bucket", "measures", "filters", "title", "rollup", "gap_fill"}


def _check_spec_types(spec: dict) -> None:
    """Reject wrongly-typed settings up front with a clear message (never let a list/dict reach code that uses it as a key)."""
    isstr = lambda v: isinstance(v, str)
    if not isstr(spec.get("doctype")):
        raise ValidationError("doctype must be a text value")
    gb = spec.get("group_by") or []
    if not isinstance(gb, list) or not all(isstr(g) for g in gb):
        raise ValidationError("group_by must be a list of field names")
    for key in ("rollup", "gap_fill"):
        if spec.get(key) is not None and not isinstance(spec[key], bool):
            raise ValidationError(f"{key} must be true or false")
    for key in ("date_field", "date_bucket", "title"):
        if spec.get(key) is not None and not isstr(spec[key]):
            raise ValidationError(f"{key} must be text")
    ms = spec.get("measures") or []
    if not isinstance(ms, list) or not all(isinstance(m, dict) and isstr(m.get("fn")) and (m.get("field") is None or isstr(m["field"]))
                                          and (m.get("label") is None or isstr(m["label"])) for m in ms):
        raise ValidationError("measures must be a list of {fn, field, label} with text values")
    fl = spec.get("filters") or []
    if not isinstance(fl, list) or not all(isinstance(f, (list, tuple)) and len(f) == 3 and isstr(f[0]) and isstr(f[1]) for f in fl):
        raise ValidationError("Filters must be [field, operator, value] triples with a text field and operator")


def prepare_adhoc(spec: dict) -> ReportDef:
    """Validate an ad-hoc spec completely (fields, measures, date bucket, filter shapes/operators/values) WITHOUT running it,
    and check read permission. Used both to run a report and to refuse a bad one at save time."""
    if not isinstance(spec, dict):
        raise ValidationError("A report definition must be an object")
    extra_keys = sorted(str(k) for k in set(spec) - SPEC_KEYS)
    if extra_keys:
        raise ValidationError(f"Unknown report setting(s): {extra_keys}")
    _check_spec_types(spec)
    rdef = adhoc_definition(spec)
    meta = registry.get(rdef.ref_doctype)                          # DoesNotExistError for an unknown DocType
    cols = set(meta.column_names())
    ftype = lambda f: meta.get_field(f).fieldtype if meta.get_field(f) else None  # noqa: E731
    NUM, ORD = ("Int", "Float", "Currency"), ("Int", "Float", "Currency", "Date", "Datetime")
    ok = lambda m: (m["field"] in cols) if m["fn"] == "count_distinct" else (ftype(m["field"]) in (ORD if m["fn"] in ("min", "max") else NUM))      # noqa: E731
    problems = [g for g in rdef.group_by if g not in cols] + [m["field"] for m in rdef.measures if m.get("field") and not ok(m)]
    if problems:
        raise ValidationError(f"Invalid field(s): {problems}")
    if rdef.date_bucket:
        df = meta.get_field(rdef.date_field) if rdef.date_field else None
        if rdef.date_field not in rdef.group_by or not ((df and df.fieldtype in ("Date", "Datetime")) or rdef.date_field in ("creation", "modified")):
            raise ValidationError("A date bucket needs a Date/Datetime field that is also one of the group-by fields")
    check_permission(meta, "read")
    extra = spec.get("filters") or []
    if not isinstance(extra, list) or not all(isinstance(fl, (list, tuple)) and len(fl) == 3 for fl in extra):
        raise ValidationError("Filters must be [field, operator, value] triples")
    if len(extra) > 20:
        raise ValidationError("At most 20 filters")
    label = lambda f: (meta.get_field(f).label if meta.get_field(f) and meta.get_field(f).label else f.replace("_", " ").title())
    rdef.filters = [ReportFilter(f"f{i}", label(str(fl[0])), "Any", field=fl[0], op=str(fl[1])) for i, fl in enumerate(extra)]
    from ..db.tables import get_table
    from ..document.document import _conditions
    _conditions(meta.name, get_table(meta.name), cols, [list(fl) for fl in extra], meta)     # raises on unknown field / operator / bad value
    return rdef


def run_adhoc(spec: dict) -> ReportResult:
    rdef = prepare_adhoc(spec)
    return run_definition(rdef, {f"f{i}": fl[2] for i, fl in enumerate(spec.get("filters") or [])})
