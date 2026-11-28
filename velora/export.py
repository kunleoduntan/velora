"""Excel (.xlsx) export, generated server-side so permissions, filters and limits are enforced in one place.

Two scopes:
  * current view : exactly the columns the user sees, in order, with the active filters + sort
  * all fields   : every field (+ system fields), and each child table on its own sheet keyed to its parent

Always requires the DocType's `export` permission, is capped at EXPORT_MAX_ROWS, and is written to
`velora_export_log` (who/what/how many rows). Text is always written as text - a cell such as
"=HYPERLINK(...)" can never become a live formula (spreadsheet formula injection).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from datetime import date, datetime
from decimal import Decimal

import xlsxwriter
from sqlalchemy import insert, select

from . import db
from .db.system import export_log
from .db.tables import get_table
from .document.document import get_list, now
from .exceptions import ValidationError
from .meta.registry import registry
from .permissions import check_permission, get_session
from .reporting.excel import FONT, _esc_footer
from .theme import current_excel_palette

EXPORT_MAX_ROWS = 50_000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_SYSTEM_LABELS = {"name": "ID", "owner": "Created By", "creation": "Created On", "modified": "Last Modified",
                  "modified_by": "Last Modified By", "docstatus": "Status", "idx": "Row", "parent": "Parent",
                  "parenttype": "Parent Type", "parentfield": "Parent Field"}
_DOCSTATUS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
_NUMFMT = {"Currency": "#,##0.00", "Float": "#,##0.00####", "Int": "#,##0"}


def _label(meta, col):
    f = meta.get_field(col)
    return (f.label or col.replace("_", " ").title()) if f else _SYSTEM_LABELS.get(col, col)


def _ftype(meta, col):
    f = meta.get_field(col)
    if f:
        return f.fieldtype
    return {"creation": "Datetime", "modified": "Datetime", "docstatus": "Status", "idx": "Int"}.get(col, "Data")


def _sheet_name(raw: str, used: set) -> str:
    base = re.sub(r"[\[\]:*?/\\]", " ", raw).strip()[:31] or "Sheet"
    name, n = base, 2
    while name.lower() in used:
        suffix = f" {n}"
        name, n = base[: 31 - len(suffix)] + suffix, n + 1
    used.add(name.lower())
    return name


class _Sheet:
    """A worksheet written strictly row by row (constant-memory mode) with per-column width tracking."""

    def __init__(self, wb, name, headers, fmts):
        self.ws = wb.add_worksheet(name)
        self.fmts, self.row = fmts, 1
        self.widths = [min(max(len(h) + 4, 10), 60) for h in headers]
        for c, h in enumerate(headers):
            self.ws.write_string(0, c, h, fmts["header"])
        self.ws.set_row(0, 22)
        self.ws.freeze_panes(1, 0)
        self.ncols = len(headers)

    def add(self, values, types):
        for c, (v, t) in enumerate(zip(values, types)):
            self._cell(c, v, t)
        self.row += 1

    def _cell(self, c, v, t):
        ws, r, f = self.ws, self.row, self.fmts
        if v is None or v == "":
            return
        shown = ""
        if t == "Check":
            shown = "Yes" if v else "No"
            ws.write_string(r, c, shown, f["text"])
        elif t == "Status":
            shown = _DOCSTATUS.get(v, str(v))
            ws.write_string(r, c, shown, f["text"])
        elif t in ("Int", "Float", "Currency") and isinstance(v, (int, float, Decimal)):
            ws.write_number(r, c, float(v), f[t])
            shown = f"{float(v):,.2f}"
        elif t == "Date" and isinstance(v, date) and not isinstance(v, datetime):
            ws.write_datetime(r, c, datetime(v.year, v.month, v.day), f["Date"])
            shown = "2000-01-01"
        elif t == "Datetime" and isinstance(v, datetime):
            ws.write_datetime(r, c, v, f["Datetime"])
            shown = "2000-01-01 00:00"
        else:
            shown = json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v)
            ws.write_string(r, c, shown[:32000], f["text"])      # write_string: never a formula
        self.widths[c] = max(self.widths[c], min(len(shown) + 2, 60))

    def finish(self, footer: str = "", tab: str | None = None):
        for c, w in enumerate(self.widths):
            self.ws.set_column(c, c, w)
        self.ws.set_paper(9)                                              # A4, one page wide, header row on every page
        (self.ws.set_landscape if self.ncols > 6 else self.ws.set_portrait)()
        self.ws.fit_to_pages(1, 0)
        self.ws.repeat_rows(0)
        self.ws.set_footer(f'&L&"{FONT},Regular"&8{_esc_footer(footer)}&C&"{FONT},Regular"&8Page &P of &N&R&"{FONT},Regular"&8Exported &D')
        if tab:
            self.ws.set_tab_color(tab)
        if self.ncols:
            self.ws.autofilter(0, 0, max(self.row - 1, 0), self.ncols - 1)


def resolve_columns(meta, columns, all_fields):
    valid = set(meta.column_names())
    if all_fields:
        cols = ["name"] + [f.fieldname for f in meta.value_fields] + ["owner", "creation", "modified", "modified_by"]
        if meta.is_submittable:
            cols.append("docstatus")
        return cols
    cols = list(dict.fromkeys(columns or (["name"] + [f.fieldname for f in meta.value_fields if f.in_list_view])))
    bad = [c for c in cols if c not in valid]
    if bad:
        raise ValidationError(f"{meta.name}: cannot export unknown column(s) {bad}")
    return cols


def export_xlsx(doctype: str, *, filters=None, columns=None, all_fields: bool = False, names=None,
                order_by: str | None = None, header: str = "label", limit: int = EXPORT_MAX_ROWS, palette: dict | None = None):
    """Returns (xlsx_bytes, filename, row_count)."""
    meta = registry.get(doctype)
    check_permission(meta, "read")
    check_permission(meta, "export")
    if header not in ("label", "fieldname"):
        raise ValidationError("header must be 'label' or 'fieldname'")
    limit = max(1, min(int(limit), EXPORT_MAX_ROWS))
    cols = resolve_columns(meta, columns, all_fields)
    types = [_ftype(meta, c) for c in cols]
    heads = [_label(meta, c) if header == "label" else c for c in cols]
    flt = [list(f) for f in (filters or [])]
    if names:
        if len(names) > 5000:
            raise ValidationError("Too many selected rows to export (max 5000); export by filter instead")
        flt.append(["name", "in", list(names)])

    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        wb = xlsxwriter.Workbook(path, {"constant_memory": True, "strings_to_formulas": False,
                                        "strings_to_urls": False, "strings_to_numbers": False})
        pal = {**{"header_bg": "d5e9ff", "header_text": "0b3a63", "rule": "3b82c4", "text": "1f2933"}, **(palette or current_excel_palette())}
        base = {"font_name": FONT, "font_size": 10, "font_color": "#" + pal["text"]}
        fm = {
            "header": wb.add_format({**base, "bold": True, "font_color": "#" + pal["header_text"], "bg_color": "#" + pal["header_bg"],
                                     "bottom": 2, "bottom_color": "#" + pal["rule"], "valign": "vcenter"}),
            "text": wb.add_format({**base, "valign": "top"}),
            "Date": wb.add_format({**base, "num_format": "yyyy-mm-dd", "align": "left"}),
            "Datetime": wb.add_format({**base, "num_format": "yyyy-mm-dd hh:mm", "align": "left"}),
            **{k: wb.add_format({**base, "num_format": v}) for k, v in _NUMFMT.items()},
        }
        used: set = set()
        main = _Sheet(wb, _sheet_name(doctype, used), heads, fm)
        children = []
        if all_fields:
            for tf in meta.table_fields:
                cm = registry.get(tf.options)
                ccols = ["parent", "idx"] + [f.fieldname for f in cm.value_fields]
                sheet = _Sheet(wb, _sheet_name(_label(meta, tf.fieldname), used),
                               [_label(cm, c) if header == "label" else c for c in ccols], fm)
                children.append((tf, cm, ccols, [_ftype(cm, c) for c in ccols], sheet))

        total = 0
        with db.transaction() as conn:
            offset = 0
            while total < limit:
                page = get_list(doctype, filters=flt, fields=cols, order_by=order_by,
                                limit=min(1000, limit - total), offset=offset)
                if not page:
                    break
                for r in page:
                    main.add([r[c] for c in cols], types)
                if children:
                    parents = [r["name"] for r in page] if "name" in cols else None
                    if parents is None:   # all_fields always includes name, but stay safe
                        parents = [r["name"] for r in get_list(doctype, filters=flt, fields=["name"], limit=len(page), offset=offset)]
                    for tf, cm, ccols, ctypes, sheet in children:
                        ct = get_table(cm.name)
                        q = select(*[ct.c[c] for c in ccols]).where(
                            ct.c.parent.in_(parents), ct.c.parenttype == doctype, ct.c.parentfield == tf.fieldname)
                        order = {p: i for i, p in enumerate(parents)}
                        rows = sorted(conn.execute(q).mappings(), key=lambda x: (order[x["parent"]], x["idx"] or 0))
                        for cr in rows:
                            sheet.add([cr[c] for c in ccols], ctypes)
                total += len(page)
                offset += len(page)
                if len(page) < 1000:
                    break

            main.finish(f"{doctype} export", "#" + pal["rule"])
            for *_, sheet in children:
                sheet.finish(f"{doctype} export", "#" + pal["rule"])
            info = wb.add_worksheet(_sheet_name("Export info", used))
            bold = wb.add_format({"bold": True})
            lines = [("DocType", doctype), ("Scope", "All fields" if all_fields else "Current view"),
                     ("Rows exported", total), ("Row limit reached", "Yes" if total >= limit else "No"),
                     ("Filters", json.dumps(flt, default=str) if flt else "None"),
                     ("Exported by", get_session().user), ("Exported at (UTC)", now().strftime("%Y-%m-%d %H:%M:%S"))]
            for i, (k, v) in enumerate(lines):
                info.write_string(i, 0, k, bold)
                (info.write_number if isinstance(v, int) else info.write_string)(i, 1, v)
            info.set_column(0, 0, 20)
            info.set_column(1, 1, 80)

            conn.execute(insert(export_log).values(
                name=secrets.token_hex(8), ref_doctype=doctype, owner=get_session().user, creation=now(),
                scope="all_fields" if all_fields else "view", row_count=total,
                detail={"columns": cols, "filters": flt, "selected": len(names or [])}))
        wb.set_properties({"title": f"{doctype} export", "author": get_session().user, "comments": "Generated by Velora"})
        wb.close()
        with open(path, "rb") as fh:
            data = fh.read()
    finally:
        if os.path.exists(path):
            os.remove(path)
    filename = f"{re.sub(r'[^A-Za-z0-9]+', '_', doctype).strip('_')}_{now().strftime('%Y%m%d_%H%M')}.xlsx"
    return data, filename, total
