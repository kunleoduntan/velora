"""Report definitions: <app>/<module>/report/<name>/<name>.json (+ <name>.py for script reports)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..exceptions import MetaError

FILTER_TYPES = ("Data", "Select", "Link", "Date", "Check", "Int", "Float", "Currency")
MEASURE_FNS = ("sum", "count", "avg", "min", "max", "count_distinct", "median", "percentile", "stddev")
PG_ONLY_FNS = ("median", "percentile", "stddev")        # need PostgreSQL (ordered-set / statistical aggregates)
DATE_BUCKETS = ("day", "month", "quarter", "year")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 &'()-]{0,80}$")


@dataclass
class ReportFilter:
    fieldname: str
    label: str
    fieldtype: str = "Data"
    options: list | str | None = None
    default: object = None
    required: bool = False
    field: str | None = None           # summary reports: the DocType field this filter applies to (default: same name)
    op: str = "="                      # summary reports: comparison operator

    def to_dict(self):
        return {"fieldname": self.fieldname, "label": self.label, "fieldtype": self.fieldtype, "options": self.options,
                "default": self.default, "required": self.required}


@dataclass
class ReportDef:
    name: str
    module: str = ""
    app: str = ""
    type: str = "script"                # script | summary
    ref_doctype: str = ""
    roles: list = field(default_factory=list)
    filters: list = field(default_factory=list)
    description: str = ""
    # summary reports
    group_by: list = field(default_factory=list)
    measures: list = field(default_factory=list)
    date_field: str | None = None
    date_bucket: str | None = None
    rollup: bool = False                # PostgreSQL: true subtotals/totals (averages, medians ...) computed by the database via GROUP BY ROLLUP
    gap_fill: bool = False              # a time series shows every period, with zeros for the empty ones
    source: str = ""
    controller_module: str = ""

    @classmethod
    def from_dict(cls, d: dict, app: str = "", source: str = "") -> "ReportDef":
        errors = []
        name = d.get("name")
        if not name or not NAME_RE.match(str(name)):
            raise MetaError(f"{source}: report needs a 'name' (letters, digits, spaces)")
        rtype = d.get("type", "script")
        if rtype not in ("script", "summary"):
            errors.append("type must be 'script' or 'summary'")
        filters = []
        for i, f in enumerate(d.get("filters", [])):
            fn, ft = f.get("fieldname"), f.get("fieldtype", "Data")
            if not fn or not re.match(r"^[a-z][a-z0-9_]*$", fn):
                errors.append(f"filter #{i + 1}: invalid fieldname")
                continue
            if ft not in FILTER_TYPES:
                errors.append(f"filter {fn}: unknown fieldtype {ft!r}")
                continue
            opts = f.get("options")
            if ft == "Select":
                opts = opts if isinstance(opts, list) else str(opts or "").split("\n")
                opts = [str(o).strip() for o in opts if str(o).strip()]
                if not opts:
                    errors.append(f"filter {fn}: Select needs options")
            if ft == "Link" and not opts:
                errors.append(f"filter {fn}: Link needs options (target DocType)")
            filters.append(ReportFilter(fn, f.get("label") or fn.replace("_", " ").title(), ft, opts, f.get("default"),
                                        bool(f.get("required")), f.get("field"), f.get("op", "=")))
        rd = cls(name=name, module=d.get("module", ""), app=app, type=rtype, ref_doctype=d.get("ref_doctype", ""),
                 roles=list(d.get("roles", [])), filters=filters, description=d.get("description", ""),
                 group_by=list(d.get("group_by", [])), measures=list(d.get("measures", [])), date_field=d.get("date_field"),
                 date_bucket=d.get("date_bucket"), rollup=bool(d.get("rollup")), gap_fill=bool(d.get("gap_fill")), source=source)
        if rtype == "summary":
            if not rd.ref_doctype:
                errors.append("a summary report needs ref_doctype")
            if not rd.group_by or len(rd.group_by) > 2:
                errors.append("group_by needs 1 or 2 fields")
            if not rd.measures:
                errors.append("a summary report needs at least one measure")
            for m in rd.measures:
                if m.get("fn") not in MEASURE_FNS:
                    errors.append(f"measure fn must be one of {', '.join(MEASURE_FNS)}")
                if m.get("fn") != "count" and not m.get("field"):
                    errors.append(f"measure {m.get('fn')} needs a field")
                if m.get("fn") == "percentile" and not (isinstance(m.get("p"), (int, float)) and not isinstance(m.get("p"), bool) and 0 < m["p"] < 100):
                    errors.append("a percentile measure needs p between 0 and 100 (e.g. 90)")
                w = m.get("where")
                if w is not None and (not isinstance(w, list) or not all(isinstance(x, list) and len(x) == 3 and isinstance(x[0], str) and isinstance(x[1], str) for x in w)):
                    errors.append("a measure's 'where' must be a list of [field, operator, value]")
            if rd.date_bucket and rd.date_bucket not in DATE_BUCKETS:
                errors.append(f"date_bucket must be one of {', '.join(DATE_BUCKETS)}")
            if rd.gap_fill and not (rd.date_bucket and rd.date_field and rd.group_by == [rd.date_field]):
                errors.append("gap_fill needs the date field as the ONLY group_by, with a date_bucket")
        if errors:
            raise MetaError(f"Invalid report {name!r} ({source}):\n  - " + "\n  - ".join(errors), details=errors)
        return rd

    def to_dict(self):
        return {"name": self.name, "module": self.module, "type": self.type, "ref_doctype": self.ref_doctype,
                "description": self.description, "filters": [f.to_dict() for f in self.filters]}
