"""Declarative "summary" reports: group a DocType by 1-2 fields and aggregate - no code needed.

    {"type": "summary", "ref_doctype": "Sales Order", "group_by": ["customer"], "date_field": "order_date", "date_bucket": "month",
     "measures": [{"fn": "count", "label": "Orders"}, {"fn": "sum", "field": "total", "label": "Revenue"}]}
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import Integer, and_, case, cast, func, select

from .. import db, site as site_mod
from ..document.document import _conditions
from ..permissions import row_policy_sql
from ..db.tables import get_table
from ..exceptions import ValidationError
from ..meta.registry import registry
from ..permissions import check_permission
from .definition import PG_ONLY_FNS
from .model import Column, ReportBuilder

_STATUS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
_PG_FMT = {"day": "YYYY-MM-DD", "month": "YYYY-MM", "quarter": 'YYYY-"Q"Q', "year": "YYYY"}
_LITE_FMT = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}


def bucket_expr(col, bucket: str, dialect: str):
    """Group a date column into day/month/quarter/year - one expression per database dialect."""
    if dialect == "sqlite":
        if bucket == "quarter":
            m = cast(func.strftime("%m", col), Integer)
            return func.strftime("%Y", col) + "-" + case((m <= 3, "Q1"), (m <= 6, "Q2"), (m <= 9, "Q3"), else_="Q4")
        return func.strftime(_LITE_FMT[bucket], col)
    return func.to_char(col, _PG_FMT[bucket])        # PostgreSQL / Oracle


def _periods(first: str, last: str, bucket: str) -> list[str]:
    """Every period label from `first` to `last` inclusive, e.g. 2026-01 ... 2026-06."""
    def parse(x):
        y = int(x[:4])
        if bucket == "year":
            return y, 1, 1
        if bucket == "quarter":
            return y, (int(x[-1]) - 1) * 3 + 1, 1
        return (y, int(x[5:7]), int(x[8:10]) if bucket == "day" else 1)
    (y, m, d), (y2, m2, d2), out = parse(first), parse(last), []
    cur, end = date(y, m, d), date(y2, m2, d2)
    while cur <= end:
        out.append(cur.strftime({"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}[bucket]) if bucket != "quarter" else f"{cur.year}-Q{(cur.month - 1) // 3 + 1}")
        if bucket == "day":
            cur = date.fromordinal(cur.toordinal() + 1)
        else:
            step = {"month": 1, "quarter": 3, "year": 12}[bucket]
            mm = cur.month - 1 + step
            cur = date(cur.year + mm // 12, mm % 12 + 1, 1)
    return out


def _num(v):
    return float(v) if isinstance(v, (Decimal, int, float)) and not isinstance(v, bool) else v


def run_summary(rdef, filters: dict) -> "ReportBuilder":
    meta = registry.get(rdef.ref_doctype)
    check_permission(meta, "read")
    t = get_table(meta.name)
    cols = set(meta.column_names())

    flt = []
    for f in rdef.filters:
        v = filters.get(f.fieldname)
        if v in (None, "", False) and f.fieldtype != "Check":
            continue
        if f.fieldname in ("from_date", "to_date") and not f.field:
            target, op = rdef.date_field, (">=" if f.fieldname == "from_date" else "<=")
        else:
            target, op = f.field or f.fieldname, f.op
        if target not in cols:
            raise ValidationError(f"Report {rdef.name}: filter {f.fieldname} refers to unknown field {target!r}")
        fld = meta.get_field(target)
        if isinstance(v, date) and not isinstance(v, datetime) and fld is not None and fld.fieldtype == "Datetime" and op == "<=":
            v = datetime.combine(v, time.max)                       # "to 7 Nov" includes the whole of 7 Nov
        flt.append([target, op, v.isoformat() if isinstance(v, (date, datetime)) else v])
    if meta.is_submittable:
        flt.append(["docstatus", "<", 2])                            # cancelled documents never count
    conds = _conditions(meta.name, t, cols, flt, meta)
    row_scope = row_policy_sql(meta.name, "read", t)
    if row_scope is not None:
        conds.append(row_scope)

    dialect = site_mod.current().engine.dialect.name
    gexprs, glabels = [], []
    for g in rdef.group_by:
        e = t.c[g]
        f = meta.get_field(g)
        if g == rdef.date_field and rdef.date_bucket:
            e = bucket_expr(e, rdef.date_bucket, dialect)
        gexprs.append(e.label(f"g_{len(gexprs)}"))
        glabels.append((f.label if f and f.label else g.replace("_", " ").title()) + (f" ({rdef.date_bucket})" if g == rdef.date_field and rdef.date_bucket else ""))

    mexprs, mcols = [], []
    for i, m in enumerate(rdef.measures):
        fn, fld = m["fn"], m.get("field")
        src = meta.get_field(fld) if fld else None
        col = t.c[fld] if fld else None
        if fn in PG_ONLY_FNS and dialect != "postgresql":
            raise ValidationError(f"The '{fn}' measure needs PostgreSQL (this database is {dialect}). Use sum/count/avg/min/max/count_distinct, or move to PostgreSQL.")
        expr = {"count": lambda: func.count(), "sum": lambda: func.sum(col), "avg": lambda: func.avg(col), "min": lambda: func.min(col), "max": lambda: func.max(col),
                "count_distinct": lambda: func.count(col.distinct()) if col is not None else func.count(), "stddev": lambda: func.stddev_samp(col),
                "median": lambda: func.percentile_cont(0.5).within_group(col), "percentile": lambda: func.percentile_cont(m.get("p", 50) / 100).within_group(col)}[fn]()
        if m.get("where"):
            expr = expr.filter(and_(*_conditions(meta.name, t, cols, [list(x) for x in m["where"]], meta)))      # a conditional measure: SUM(x) FILTER (WHERE ...)
        mexprs.append(expr.label(f"m_{i}"))
        label = m.get("label") or ("Count" if fn == "count" else f"{fn.replace('_', ' ').title()}{'' if fn != 'percentile' else ' ' + str(m.get('p'))} of {src.label or fld}")
        additive = fn in ("sum", "count")                      # only these can be added up across groups
        ftype = "Int" if fn in ("count", "count_distinct") else ("Float" if fn in ("avg", "median", "percentile", "stddev") and src.fieldtype != "Currency" else src.fieldtype)
        mcols.append(Column(f"m_{i}", label, ftype, total="sum" if additive else "none"))

    ng = len(rdef.group_by)
    # NULL groups sort LAST on every database (SQLite puts them first, PostgreSQL last) so a report never reorders between engines
    nulls_last = lambda e: (case((e.is_(None), 1), else_=0), e)  # noqa: E731
    if getattr(rdef, "rollup", False):
        if dialect != "postgresql":
            raise ValidationError(f"Report {rdef.name}: 'rollup' needs PostgreSQL (this database is {dialect}). Without it, subtotals of averages and medians cannot be correct.")
        grp = [func.grouping(e) for e in gexprs]
        order = [x for g, e in zip(grp, gexprs, strict=True) for x in (g, *nulls_last(e))]
        stmt = select(*gexprs, *grp, *mexprs).group_by(func.rollup(*gexprs)).order_by(*order)          # one query: details + subtotals + grand total, all computed by the database
    else:
        stmt = select(*gexprs, *mexprs).group_by(*gexprs).order_by(*[x for e in gexprs for x in nulls_last(e)])
    for c in conds:
        stmt = stmt.where(c)
    with db.transaction() as conn:
        data = [tuple(r) for r in conn.execute(stmt)]

    if getattr(rdef, "gap_fill", False) and ng == 1 and rdef.date_bucket and not getattr(rdef, "rollup", False):
        have = {r[0] for r in data if r[0] is not None}
        if have:                                                    # every period between the first and the last, empty ones with zero
            empty = tuple(0 if m["fn"] in ("sum", "count", "count_distinct") else None for m in rdef.measures)
            data = sorted([r for r in data if r[0] is not None] + [(p, *empty) for p in _periods(min(have), max(have), rdef.date_bucket) if p not in have]) + [r for r in data if r[0] is None]

    def show(g, v):
        if v is None or v == "":
            return "(none)"
        return _STATUS.get(v, v) if g == "docstatus" else str(v)

    rb = ReportBuilder(rdef.name, [Column("label", " / ".join(glabels), "Data"), *mcols])
    mvals = lambda row, start: {c.fieldname: _num(v) for c, v in zip(mcols, row[start:], strict=True)}  # noqa: E731
    if getattr(rdef, "rollup", False):
        offset = ng + ng                                            # group values, then their grouping() flags
        current, open_ = object(), False
        for row in data:
            flags, vals = row[ng:offset], mvals(row, offset)
            if flags[0] == 1:                                       # the grand total
                continue
            if ng == 1:
                rb.row({"label": show(rdef.group_by[0], row[0]), **vals}, indent=0)
            elif flags[1] == 1:                                     # a subtotal of one first-level group (true aggregates, not sums of rows)
                rb.subtotal(f"Total {show(rdef.group_by[0], current)}", values=vals)
                open_ = False
            else:
                if row[0] != current or not open_:
                    current, open_ = row[0], True
                    rb.section(show(rdef.group_by[0], row[0]))
                rb.row({"label": show(rdef.group_by[1], row[1]), **vals})
        grand = next((mvals(r, offset) for r in data if r[ng] == 1), None)
        if data:
            rb.total("Total", values=grand)
        return rb
    if ng == 1:
        for row in data:
            rb.row({"label": show(rdef.group_by[0], row[0]), **mvals(row, 1)}, indent=0)
    else:
        current, open_ = object(), False
        for row in data:
            if row[0] != current:
                if open_:
                    rb.subtotal(f"Total {show(rdef.group_by[0], current)}")
                current, open_ = row[0], True
                rb.section(show(rdef.group_by[0], row[0]))
            rb.row({"label": show(rdef.group_by[1], row[1]), **mvals(row, 2)})
        if open_:
            rb.subtotal(f"Total {show(rdef.group_by[0], current)}")
    if data:
        rb.total("Total")
    return rb
