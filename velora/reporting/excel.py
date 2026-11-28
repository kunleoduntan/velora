"""Excel export for reports: QuickBooks-style layout in a soft, simple palette.

Layout    company name / report title / period / filters, then the table; no gridlines; section rows, indented detail,
          subtotal and total rows with rules - and REAL SUM formulas (with cached values) for every subtotal/total.
Print     A4, fit to one page wide, header row repeats on every page, "Page x of y" footer, landscape when the table is wide.
Numbers   real numbers/dates (never text), accounting formats with negatives in (parentheses) and dashes for zero.
Safe      every string is written as text, so cell content can never become a formula (formula injection).
Colour    from the active theme's Excel palette: pastel header tint, deep brand-coloured text, one confident rule colour.
"""
from __future__ import annotations

import io
import re
from decimal import Decimal
from datetime import date, datetime

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

from ..exceptions import ValidationError
from .model import MAX_ROWS, ReportResult

FONT = "Arial"
NUMFMT = {
    "Currency": '#,##0.00_);(#,##0.00);"-"_)',
    "Float": '#,##0.00_);(#,##0.00);"-"_)',
    "Int": '#,##0_);(#,##0);"-"_)',
    "Percent": '0.0%_);(0.0%);"-"_)',
    "Date": "dd/mm/yyyy",
    "Datetime": "dd/mm/yyyy hh:mm",
}
DEFAULT_WIDTH = {"Currency": 17, "Float": 15, "Int": 12, "Percent": 12, "Date": 14, "Datetime": 18, "Check": 9, "Data": 26, "Link": 26}
NUMERIC_TYPES = ("Currency", "Float", "Int", "Percent")

DEFAULT_PALETTE = {"title": "0f4c81", "header_bg": "1f3864", "header_text": "ffffff", "rule": "3b82c4", "section_bg": "f1f7fd",
                   "total_bg": "e7f1fb", "band": "eef3fa", "total_records": "ffe699", "grid": "e1e7ee", "muted": "5f6b7a", "text": "1f2933"}



def _is_num(v) -> bool:
    """int, float AND Decimal (exact money from accounting reports) - never bool."""
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _esc_footer(text: str) -> str:
    return re.sub(r"[\x00-\x1f]", "", text).replace("&", "&&")[:120]


def _sheet_name(text: str) -> str:
    return (re.sub(r"[\[\]:*?/\\]", " ", text).strip() or "Report")[:31]


def _ranges(rows: list[int], col: str) -> str:
    """Compress sorted Excel row numbers into 'C7:C9,C12' so a subtotal over 1,000 rows is one short formula."""
    rows = sorted(set(rows))
    parts, start, prev = [], None, None
    for r in rows:
        if start is None:
            start = prev = r
        elif r == prev + 1:
            prev = r
        else:
            parts.append(f"{col}{start}:{col}{prev}" if prev > start else f"{col}{start}")
            start = prev = r
    if start is not None:
        parts.append(f"{col}{start}:{col}{prev}" if prev > start else f"{col}{start}")
    return ",".join(parts)


def report_to_xlsx(result: ReportResult, palette: dict | None = None, *, user: str = "", banded: bool = True) -> bytes:
    if len(result.rows) > MAX_ROWS:
        raise ValidationError(f"Report is too large to export (more than {MAX_ROWS:,} rows)")
    pal = {**DEFAULT_PALETTE, **(palette or {})}
    P = lambda k: "#" + pal[k]
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False, "strings_to_numbers": False})
    ws = wb.add_worksheet(_sheet_name(result.title))
    cache: dict = {}

    def fmt(**kw):
        key = tuple(sorted(kw.items()))
        if key not in cache:
            cache[key] = wb.add_format({"font_name": FONT, "font_size": 10, "valign": "vcenter", "font_color": P("text"), **kw})
        return cache[key]

    cols = result.columns
    ncols = len(cols)
    label_col = 0

    # ---- title block ------------------------------------------------------------------------------
    r = 0
    if result.company:
        ws.write_string(r, 0, result.company, fmt(bold=True, font_size=16, font_color=P("title")))
        ws.set_row(r, 24)
        r += 1
    ws.write_string(r, 0, result.title, fmt(bold=True, font_size=13, font_color=P("header_text")))
    ws.set_row(r, 20)
    r += 1
    n_records = sum(1 for x in result.rows if x.type == "data")
    sub = result.subtitle + (f"   |   Amounts in {result.currency}" if result.currency else "")
    if sub.strip():
        ws.write_string(r, 0, sub.strip(), fmt(font_size=10, font_color=P("muted")))
        r += 1
    filt = "; ".join(f"{k} = {v}" if v != "" else str(k) for k, v in result.filters) if result.filters else "none"
    ws.write_string(r, 0, f"Exported on {datetime.now().strftime('%d-%m-%Y')}  |  {n_records:,} records  |  Filters: {filt}", fmt(font_size=9, font_color=P("muted"), italic=True))
    r += 1
    r += 1
    if result.summary:                                    # headline numbers as a small, quiet label/value block
        for s in result.summary:
            ws.write_string(r, 0, str(s["label"]), fmt(font_color=P("muted")))
            v, ft = s.get("value"), s.get("fieldtype", "Data")
            if _is_num(v) and ft in NUMERIC_TYPES:
                ws.write_number(r, 1, float(v), fmt(bold=True, num_format=NUMFMT[ft], align="right"))
            else:
                ws.write_string(r, 1, "" if v is None else str(v), fmt(bold=True, align="right"))
            r += 1
        r += 1

    # ---- header row ------------------------------------------------------------------------------------
    hdr = r
    for ci, col in enumerate(cols):
        ws.write_string(hdr, ci, col.label, fmt(bold=True, bg_color=P("header_bg"), font_color=P("header_text"), bottom=2, bottom_color=P("rule"),
                                                 align="right" if col.fieldtype in NUMERIC_TYPES else "left", text_wrap=True))
    ws.set_row(hdr, 24)
    if ncols and result.rows:
        ws.autofilter(hdr, 0, hdr + len(result.rows), ncols - 1)

    # ---- body -----------------------------------------------------------------------------------------------
    excel_row = {}                                        # report row index -> 1-based Excel row (for formulas)
    for idx in range(len(result.rows)):
        excel_row[idx] = hdr + 2 + idx
    widths = [max(len(c.label) + 3, DEFAULT_WIDTH.get(c.fieldtype, 20)) for c in cols]
    n_data = 0
    for idx, row in enumerate(result.rows):
        rr = hdr + 1 + idx
        t = row.type
        if t == "spacer":
            ws.set_row(rr, 6)
            continue
        base: dict = {}
        if t == "header":
            base = {"bold": True, "bg_color": P("section_bg"), "font_color": P("header_text")}
        elif t == "subtotal":
            base = {"bold": True, "top": 1, "top_color": P("rule")}
        elif t == "total":
            base = {"bold": True, "bg_color": P("total_bg"), "top": 2, "top_color": P("rule"), "bottom": 6, "bottom_color": P("rule")}
        elif banded and n_data % 2 == 1:
            base = {"bg_color": P("band")}
        if t == "data":
            n_data += 1
        for ci, col in enumerate(cols):
            v = row.values.get(col.fieldname)
            numeric = col.fieldtype in NUMERIC_TYPES
            if ci == label_col:
                text = "" if v is None else str(v)
                widths[ci] = min(max(widths[ci], len(text) + row.indent * 2 + 3), 60)
                ws.write_string(rr, ci, text, fmt(**base, indent=row.indent, align="left"))
                continue
            if t == "header":
                ws.write_blank(rr, ci, None, fmt(**base))
                continue
            f_num = fmt(**base, num_format=NUMFMT.get(col.fieldtype, "General"), align="right")
            if t in ("subtotal", "total") and col.total == "sum" and row.children is not None:
                # a REAL formula over the rows it totals, with the computed value cached for viewers that do not recalculate
                kids = [excel_row[i] for i in row.children if i in excel_row]
                cached = float(v) if _is_num(v) else 0.0
                if kids:
                    letter = xl_col_to_name(ci)
                    ws.write_formula(rr, ci, f"=SUM({_ranges(kids, letter)})", f_num, cached)
                else:
                    ws.write_number(rr, ci, 0, f_num)
                continue
            if v is None or v == "":
                ws.write_blank(rr, ci, None, fmt(**base))
            elif col.fieldtype == "Check":
                ws.write_string(rr, ci, "Yes" if v else "No", fmt(**base, align="center"))
            elif numeric and _is_num(v):
                ws.write_number(rr, ci, float(v), f_num)
                widths[ci] = max(widths[ci], len(f"{abs(v):,.2f}") + 5)
            elif col.fieldtype in ("Date", "Datetime") and isinstance(v, (date, datetime)):
                d = v if isinstance(v, datetime) else datetime(v.year, v.month, v.day)
                ws.write_datetime(rr, ci, d, fmt(**base, num_format=NUMFMT[col.fieldtype], align="left"))
            else:
                s = str(v)
                widths[ci] = min(max(widths[ci], len(s) + 3), 50)
                ws.write_string(rr, ci, s, fmt(**base, align="right" if numeric else "left"))

    for ci, col in enumerate(cols):
        ws.set_column(ci, ci, widths[ci] if not col.width else max(col.width, widths[ci]))
    foot = hdr + 1 + len(result.rows) + 1
    ws.write_string(foot, 0, f"Total records: {n_records:,}", fmt(bold=True, bg_color=P("total_records")))
    for ci in range(1, ncols):
        ws.write_blank(foot, ci, None, fmt(bg_color=P("total_records")))

    # ---- sheet, print and file properties -----------------------------------------------------------------------
    ws.hide_gridlines(2)
    ws.freeze_panes(hdr + 1, 1 if ncols > 5 else 0)
    ws.set_paper(9)                                                       # A4
    (ws.set_landscape if ncols > 6 else ws.set_portrait)()
    ws.fit_to_pages(1, 0)
    ws.repeat_rows(hdr)
    ws.set_margins(left=0.5, right=0.5, top=0.7, bottom=0.8)
    ws.set_footer(f'&L&"{FONT},Regular"&8{_esc_footer(" - ".join(x for x in (result.company, result.title) if x))}'
                  f'&C&"{FONT},Regular"&8Page &P of &N&R&"{FONT},Regular"&8Generated &D')
    ws.set_tab_color(P("rule"))
    wb.set_properties({"title": result.title, "subject": result.subtitle, "author": user or "Velora", "company": result.company,
                       "comments": f"Generated by Velora on {result.generated_at}".strip()})
    wb.close()
    return buf.getvalue()
