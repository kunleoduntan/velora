"""Form layout and grid-column definitions.

A form layout is a 12-column grid, the way a form designer (Microsoft Access, Dynamics) thinks about it:

    {"tabs": [{"label": "Details", "sections": [{"label": "Customer", "collapsible": false,
               "rows": [[{"field": "customer", "span": 6}, {"field": "posting_date", "span": 3}, {"field": "due_date", "span": 3}],
                        [{"field": "items", "span": 12}]]}]}]}

* a cell is one field with a width of 1..12 (twelfths of the row); a row's widths add up to at most 12
* every field appears at most once; fields a layout does not mention are NEVER lost - `effective_layout` appends them in a "More" section,
  so adding a field to a DocType after a layout was saved cannot make it vanish from the form
* a DocType without a layout keeps the classic Section/Column Break rendering; `derive_layout` turns that into this model as a designer's starting point
* a child table does not have a layout: it has `grid_columns` ([{"field", "width"}]): an unbounded ordered list of visible fields with independent widths
"""
from __future__ import annotations

import copy

MAX_TABS, MAX_SECTIONS, MAX_ROWS, MAX_LABEL = 12, 60, 300, 140
WIDE_TYPES = {"Table", "Text", "JSON"}


def _label(v, where: str, errors: list[str]) -> str:
    if v is None:
        return ""
    if not isinstance(v, str) or len(v) > MAX_LABEL:
        errors.append(f"{where}: label must be text of at most {MAX_LABEL} characters")
        return ""
    return v


def placeable(dt) -> dict:
    """Fields that can be placed on a form: real value fields and tables (not Section/Column/Tab breaks)."""
    return {f.fieldname: f for f in dt.fields if not f.is_layout}


def validate_layout(layout, dt) -> list[str]:
    errors: list[str] = []
    if not isinstance(layout, dict) or not isinstance(layout.get("tabs"), list):
        return ["layout must be an object with a 'tabs' list"]
    tabs = layout["tabs"]
    if not tabs:
        return ["layout needs at least one tab"]
    if len(tabs) > MAX_TABS:
        errors.append(f"at most {MAX_TABS} tabs")
    names, seen, n_sections, n_rows = placeable(dt), set(), 0, 0
    for ti, tab in enumerate(tabs, 1):
        if not isinstance(tab, dict) or not isinstance(tab.get("sections"), list):
            errors.append(f"tab {ti}: needs a 'sections' list")
            continue
        _label(tab.get("label"), f"tab {ti}", errors)
        for si, sec in enumerate(tab["sections"], 1):
            n_sections += 1
            where = f"tab {ti}, section {si}"
            if not isinstance(sec, dict) or not isinstance(sec.get("rows"), list):
                errors.append(f"{where}: needs a 'rows' list")
                continue
            _label(sec.get("label"), where, errors)
            for ri, row in enumerate(sec["rows"], 1):
                n_rows += 1
                rw = f"{where}, row {ri}"
                if not isinstance(row, list) or not row:
                    errors.append(f"{rw}: a row needs at least one cell")
                    continue
                if len(row) > 12:
                    errors.append(f"{rw}: at most 12 cells")
                total = 0
                for cell in row:
                    if not isinstance(cell, dict):
                        errors.append(f"{rw}: a cell must be an object {{field, span}}")
                        continue
                    fn, span = cell.get("field"), cell.get("span")
                    if not isinstance(fn, str) or fn not in names:
                        errors.append(f"{rw}: {fn!r} is not a field of {dt.name} (Section/Column/Tab breaks cannot be placed)")
                        continue
                    if fn in seen:
                        errors.append(f"{rw}: {fn} is placed more than once")
                    seen.add(fn)
                    if isinstance(span, bool) or not isinstance(span, int) or not 1 <= span <= 12:
                        errors.append(f"{rw}: {fn} needs a span between 1 and 12")
                        continue
                    total += span
                if total > 12:
                    errors.append(f"{rw}: the widths add up to {total}; a row holds at most 12")
    if n_sections > MAX_SECTIONS:
        errors.append(f"at most {MAX_SECTIONS} sections")
    if n_rows > MAX_ROWS:
        errors.append(f"at most {MAX_ROWS} rows")
    return errors


def normalize_layout(layout: dict) -> dict:
    """Keep only the known keys, so a stored layout can't smuggle anything else into the Desk."""
    return {"tabs": [{"label": t.get("label") or "", "sections": [
        {"label": s.get("label") or "", "collapsible": bool(s.get("collapsible")), **({"auto": True} if s.get("auto") else {}),
         "rows": [[{"field": c["field"], "span": int(c["span"])} for c in row] for row in s["rows"]]} for s in t["sections"]]} for t in layout["tabs"]]}


def _spans(n: int) -> list[int]:
    base, extra = divmod(12, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def derive_layout(dt) -> dict:
    """Frappe-style Tab/Section/Column breaks -> the grid model (columns become cells of equal width)."""
    tabs: list[dict] = []

    def tab():
        if not tabs:
            tabs.append({"label": "Details", "sections": []})
        return tabs[-1]

    def section():
        t = tab()
        if not t["sections"]:
            t["sections"].append({"label": "", "columns": [[]]})
        return t["sections"][-1]
    for f in dt.fields:
        if f.fieldtype == "Tab Break":
            tabs.append({"label": f.label or "Details", "sections": []})
        elif f.fieldtype == "Section Break":
            tab()["sections"].append({"label": f.label or "", "columns": [[]]})
        elif f.fieldtype == "Column Break":
            section()["columns"].append([])
        elif not f.hidden:
            section()["columns"][-1].append(f.fieldname)
    out = []
    for t in tabs:
        secs = []
        for s in t["sections"]:
            cols = [c for c in s["columns"] if c]
            if not cols:
                continue
            if len(cols) == 1:
                # A normal business form should use the available width sensibly: pair short
                # controls, but give long text and child tables their own full-width row.
                by_name = {f.fieldname: f for f in dt.fields}
                rows, row, used = [], [], 0
                for name in cols[0]:
                    span = 12 if by_name[name].fieldtype in WIDE_TYPES else 6
                    if used + span > 12:
                        rows.append(row); row, used = [], 0
                    row.append({"field": name, "span": span}); used += span
                    if used == 12:
                        rows.append(row); row, used = [], 0
                if row:
                    rows.append(row)
            else:
                # Explicit Column Breaks retain their familiar side-by-side semantics.
                spans = _spans(len(cols))
                rows = [[{"field": col[i], "span": spans[ci]} for ci, col in enumerate(cols) if i < len(col)] for i in range(max(len(c) for c in cols))]
            secs.append({"label": s["label"], "collapsible": False, "rows": rows})
        if secs:
            out.append({"label": t["label"], "sections": secs})
    return {"tabs": out}


def placed(layout: dict) -> set[str]:
    return {c["field"] for t in layout.get("tabs", []) for s in t["sections"] for row in s["rows"] for c in row}


def unplaced_fields(layout: dict, dt) -> list:
    p = placed(layout)
    return [f for f in dt.fields if not f.is_layout and not f.hidden and f.fieldname not in p]


def effective_layout(layout: dict, dt) -> dict:
    """The layout the form renders: the saved one plus any field it does not mention (new fields never disappear)."""
    out = copy.deepcopy(layout)
    rest = unplaced_fields(out, dt)
    if not rest:
        return out
    if not out["tabs"]:
        out["tabs"].append({"label": "Details", "sections": []})
    rows, pair = [], []
    for f in rest:
        if f.fieldtype in WIDE_TYPES:
            rows.append([{"field": f.fieldname, "span": 12}])
        else:
            pair.append({"field": f.fieldname, "span": 6})
            if len(pair) == 2:
                rows.append(pair)
                pair = []
    if pair:
        rows.append(pair)
    out["tabs"][-1]["sections"].append({"label": "More", "collapsible": False, "auto": True, "rows": rows})
    return out


def validate_grid_columns(cols, dt) -> list[str]:
    if not isinstance(cols, list) or not cols:
        return ["grid_columns must be a non-empty list of {field, width}"]
    names, seen, errors = placeable(dt), set(), []
    for i, c in enumerate(cols, 1):
        fn, w = (c.get("field"), c.get("width")) if isinstance(c, dict) else (None, None)
        if fn not in names or names[fn].fieldtype == "Table":
            errors.append(f"column {i}: {fn!r} is not a field that can be shown in a grid")
            continue
        if fn in seen:
            errors.append(f"column {i}: {fn} appears twice")
        seen.add(fn)
        if isinstance(w, bool) or not isinstance(w, int) or not 1 <= w <= 100:
            errors.append(f"column {i}: width must be an integer between 1 and 100")
            continue
    return errors


def normalize_grid_columns(cols: list) -> list:
    return [{"field": c["field"], "width": int(c["width"])} for c in cols]
