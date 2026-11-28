"""The report result model: one structure for everything a report can show, and the only thing the Desk and Excel render.

A report is a table of typed columns and typed ROWS (section header, data, subtotal, total, spacer) with an indent level -
which is what makes accounting-style reports (Profit & Loss, aging, sales by group) possible, not just flat lists.
Subtotal/total rows remember which rows they sum (`children`), so the Excel export can write real SUM formulas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from ..exceptions import ValidationError

COLUMN_TYPES = ("Data", "Link", "Currency", "Float", "Int", "Percent", "Date", "Datetime", "Check")
NUMERIC = ("Currency", "Float", "Int")                # summed in subtotals by default (Percent is not additive)
ROW_TYPES = ("data", "header", "subtotal", "total", "spacer")
MAX_ROWS = 100_000


@dataclass
class Column:
    fieldname: str
    label: str
    fieldtype: str = "Data"
    width: int | None = None
    total: str | None = None            # "sum" (default for numeric) | "none"

    def __post_init__(self):
        if self.fieldtype not in COLUMN_TYPES:
            raise ValidationError(f"Column {self.fieldname!r}: unknown type {self.fieldtype!r}")
        if self.total is None:
            self.total = "sum" if self.fieldtype in NUMERIC else "none"

    def to_dict(self):
        return {"fieldname": self.fieldname, "label": self.label, "fieldtype": self.fieldtype, "width": self.width, "total": self.total}


@dataclass
class Row:
    type: str = "data"
    values: dict = field(default_factory=dict)
    indent: int = 0
    children: list | None = None        # row indexes this subtotal/total sums

    def to_dict(self):
        return {"type": self.type, "values": self.values, "indent": self.indent, "children": self.children}


@dataclass
class ReportResult:
    title: str
    columns: list
    rows: list
    subtitle: str = ""
    filters: list = field(default_factory=list)      # [(label, shown value)] - printed under the title
    summary: list = field(default_factory=list)      # [{label, value, fieldtype}] headline numbers
    notes: list = field(default_factory=list)
    currency: str = ""
    company: str = ""
    report_name: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        def clean(v):
            return v.isoformat() if isinstance(v, (date, datetime)) else (float(v) if hasattr(v, "as_tuple") else v)
        return {"title": self.title, "subtitle": self.subtitle, "columns": [c.to_dict() for c in self.columns],
                "rows": [{**r.to_dict(), "values": {k: clean(v) for k, v in r.values.items()}} for r in self.rows],
                "filters": [list(f) for f in self.filters],
                "summary": [{**s, "value": clean(s["value"])} for s in self.summary], "notes": self.notes,
                "currency": self.currency, "company": self.company, "report_name": self.report_name, "generated_at": self.generated_at}


class ReportBuilder:
    """Assemble hierarchical reports without hand-writing totals.

        rb = ReportBuilder("Sales by Group", [Column("name", "Customer"), Column("amount", "Amount", "Currency")])
        rb.section("Retail")                    # header row, opens a group
        rb.row({"name": "Acme", "amount": 100})   # indented under the open group
        rb.subtotal("Total Retail")             # closes the group: sums its rows, remembers which
        rb.total("TOTAL")                       # grand total over everything at the top level
    """

    def __init__(self, title: str, columns: list[Column], subtitle: str = "", currency: str = ""):
        if not columns:
            raise ValidationError("A report needs at least one column")
        self.title, self.columns, self.subtitle, self.currency = title, columns, subtitle, currency
        self.rows: list[Row] = []
        self._stack: list[list[int]] = []            # children of each open group
        self._root: list[int] = []

    def _add(self, row: Row) -> int:
        if len(self.rows) >= MAX_ROWS:
            raise ValidationError(f"Report is too large (more than {MAX_ROWS:,} rows); narrow the filters")
        self.rows.append(row)
        return len(self.rows) - 1

    @property
    def _label_col(self) -> str:
        return self.columns[0].fieldname

    def _sums(self, children: list[int]) -> dict:
        out = {}
        for col in self.columns:
            if col.total != "sum":
                continue
            vals = [self.rows[i].values.get(col.fieldname) for i in children]
            nums = [v for v in vals if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)]
            # exact decimal arithmetic: float addition would show 0.1 + 0.2 as 0.30000000000000004 in a financial total
            out[col.fieldname] = sum((v if isinstance(v, Decimal) else Decimal(str(v)) for v in nums), Decimal(0)) if nums else None
        return out

    def section(self, label: str, indent: int | None = None) -> int:
        i = self._add(Row("header", {self._label_col: label}, len(self._stack) if indent is None else indent))
        self._stack.append([])
        return i

    def row(self, values: dict, indent: int | None = None) -> int:
        i = self._add(Row("data", dict(values), len(self._stack) if indent is None else indent))
        (self._stack[-1] if self._stack else self._root).append(i)
        return i

    def _extra(self, values: dict | None) -> dict:
        """Values supplied by the database for columns that cannot be added up (averages, medians ...). Additive columns always use the exact sums/formulas."""
        add = {c.fieldname for c in self.columns if c.total == "sum"}
        return {k: v for k, v in (values or {}).items() if k not in add}

    def subtotal(self, label: str, values: dict | None = None) -> int:
        if not self._stack:
            raise ValidationError("subtotal() needs an open section()")
        children = self._stack.pop()
        i = self._add(Row("subtotal", {self._label_col: label, **self._extra(values), **self._sums(children)}, len(self._stack), children=children))
        (self._stack[-1] if self._stack else self._root).append(i)
        return i

    def total(self, label: str = "Total", values: dict | None = None) -> int:
        while self._stack:                                       # close anything left open so totals are never silently wrong
            self.subtotal("Total")
        children = list(self._root)
        return self._add(Row("total", {self._label_col: label, **self._extra(values), **self._sums(children)}, 0, children=children))

    def spacer(self) -> int:
        return self._add(Row("spacer"))

    def build(self, filters=None, summary=None, notes=None, subtitle: str | None = None) -> ReportResult:
        return ReportResult(self.title, self.columns, self.rows, subtitle if subtitle is not None else self.subtitle,
                            filters or [], summary or [], notes or [], self.currency)
