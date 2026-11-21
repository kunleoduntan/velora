import io
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

import velora
from velora import db, new_doc
from velora.api import create_app
from velora.db.system import export_log
from velora.exceptions import DoesNotExistError, MetaError, PermissionDenied, ValidationError
from velora.reporting import Column, ReportBuilder, ReportResult
from velora.reporting.definition import ReportDef
from velora.reporting.excel import MAX_ROWS, _ranges, report_to_xlsx
from velora.reporting.runner import normalize_filters, run_adhoc, run_report
from velora.settings import set_setting

SALES = {"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}
ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
NOBODY = {"X-Velora-User": "nobody", "X-Velora-Roles": ""}
cols = lambda: [Column("name", "Name"), Column("qty", "Qty", "Int"), Column("amt", "Amount", "Currency"), Column("pct", "Share", "Percent")]


# ============================ builder ============================
def test_builder_sums_children_and_remembers_which_rows():
    rb = ReportBuilder("T", cols())
    rb.section("A")
    i1 = rb.row({"name": "x", "qty": 1, "amt": 10.5, "pct": .5})
    i2 = rb.row({"name": "y", "qty": 2, "amt": 20, "pct": .5})
    sub = rb.subtotal("Total A")
    rb.section("B")
    i3 = rb.row({"name": "z", "qty": 4, "amt": 5})
    sub2 = rb.subtotal("Total B")
    tot = rb.total("TOTAL")
    r = rb.rows
    assert r[sub].values == {"name": "Total A", "qty": 3.0, "amt": 30.5} and r[sub].children == [i1, i2]
    assert r[sub2].children == [i3] and r[tot].children == [sub, sub2]                 # the grand total sums SUBTOTALS: no double counting
    assert r[tot].values["amt"] == 35.5 and r[tot].values["qty"] == 7.0
    assert "pct" not in r[sub].values                                                  # percentages are not additive: never summed
    assert [x.indent for x in r[:3]] == [0, 1, 1] and r[sub].indent == 0 and r[tot].indent == 0


def test_builder_nested_sections_and_unclosed_groups():
    rb = ReportBuilder("T", cols())
    rb.section("Assets"); rb.section("Current"); a = rb.row({"name": "Cash", "amt": 5}); rb.subtotal("Total Current")
    rb.section("Fixed"); rb.row({"name": "Land", "amt": 7})                           # left unclosed on purpose
    tot = rb.total("Net")                                                             # total() closes open groups instead of lying
    assert rb.rows[tot].values["amt"] == 12.0
    assert [x.type for x in rb.rows].count("subtotal") == 3                     # Current (closed), then Fixed and Assets closed by total()
    assert rb.rows[a].indent == 2


def test_builder_guards():
    rb = ReportBuilder("T", cols())
    with pytest.raises(ValidationError, match="open section"):
        rb.subtotal("x")
    with pytest.raises(ValidationError):
        ReportBuilder("T", [])
    with pytest.raises(ValidationError, match="unknown type"):
        Column("a", "A", "Nonsense")
    rb.row({"name": "only", "amt": None})
    assert rb.rows[rb.total("T")].values["amt"] is None                               # nothing to sum: blank, not a misleading 0
    assert rb.spacer() == 2 and rb.rows[2].type == "spacer"


def test_result_serialises_dates_and_decimals():
    from decimal import Decimal
    rb = ReportBuilder("T", [Column("d", "Date", "Date"), Column("a", "A", "Currency")])
    rb.row({"d": date(2026, 1, 2), "a": Decimal("12.50")})
    d = rb.build(summary=[{"label": "x", "value": Decimal("1.5"), "fieldtype": "Float"}]).to_dict()
    json.dumps(d)
    assert d["rows"][0]["values"] == {"d": "2026-01-02", "a": 12.5} and d["summary"][0]["value"] == 1.5


# ============================ definitions ============================
def test_definition_validation_reports_all_problems():
    with pytest.raises(MetaError) as e:
        ReportDef.from_dict({"name": "R", "type": "summary", "filters": [{"fieldname": "Bad Name"}, {"fieldname": "s", "fieldtype": "Select"},
                            {"fieldname": "l", "fieldtype": "Link"}], "measures": [{"fn": "mode"}], "date_bucket": "week"}, source="t")
    msg = str(e.value)
    for frag in ("invalid fieldname", "Select needs options", "Link needs options", "needs ref_doctype", "group_by needs", "measure fn must be", "date_bucket"):
        assert frag in msg, frag
    with pytest.raises(MetaError, match="needs a 'name'"):
        ReportDef.from_dict({"type": "script"})


def test_registry_discovers_demo_reports_and_cross_validates(site):
    names = {r.name for r in velora.registry.reports()}
    assert {"Sales by Customer Group", "Credit Exposure by Group"} <= names
    from velora.meta.registry import Registry
    reg = Registry()
    reg.load(["velora_demo"])
    for bad, frag in (({"name": "X1", "type": "summary", "ref_doctype": "Nope", "group_by": ["a"], "measures": [{"fn": "count"}]}, "not a DocType"),
                      ({"name": "X2", "type": "summary", "ref_doctype": "Customer", "group_by": ["nope"], "measures": [{"fn": "count"}]}, "does not exist"),
                      ({"name": "X3", "type": "summary", "ref_doctype": "Customer", "group_by": ["status"], "measures": [{"fn": "sum", "field": "customer_name"}]}, "numeric"),
                      ({"name": "X4", "type": "summary", "ref_doctype": "Customer", "group_by": ["status"], "measures": [{"fn": "count"}], "date_bucket": "month"}, "date_bucket needs"),
                      ({"name": "X5", "type": "script", "filters": [{"fieldname": "g", "fieldtype": "Link", "options": "Ghost"}]}, "unknown DocType")):
        reg._reports = {}
        rd = ReportDef.from_dict(bad, app="velora_demo", source="t")
        rd.controller_module = "velora_demo.demo.report.sales_by_customer_group.sales_by_customer_group"
        reg._reports[rd.name] = rd
        with pytest.raises(MetaError, match=frag):
            reg._cross_validate()


# ============================ filters ============================
def test_filter_normalisation(site):
    rd = velora.registry.report("Sales by Customer Group")
    f = normalize_filters(rd, {"to_date": "2026-03-01", "customer_group": ""})
    assert f["to_date"] == date(2026, 3, 1) and f["from_date"].month == 1 and f["from_date"].day == 1 and "customer_group" not in f    # defaults: Year Start
    with pytest.raises(ValidationError, match="unknown filter"):
        normalize_filters(rd, {"bogus": 1})
    with pytest.raises(ValidationError, match="not a valid Date"):
        normalize_filters(rd, {"from_date": "tomorrow"})
    sel = velora.registry.report("Credit Exposure by Group")
    assert normalize_filters(sel, {"status": "Active"}) == {"status": "Active"}
    with pytest.raises(ValidationError, match="must be one of"):
        normalize_filters(sel, {"status": "Weird"})
    req = ReportDef.from_dict({"name": "R", "filters": [{"fieldname": "n", "fieldtype": "Int", "required": True}]})
    with pytest.raises(ValidationError, match="required"):
        normalize_filters(req, {})
    assert normalize_filters(req, {"n": "5"}) == {"n": 5}


# ============================ running ============================
def seed():
    for g in ("Retail", "Wholesale"):
        new_doc("Customer Group", group_name=g).insert()
    specs = [("Acme", "Retail", "Active", 1000), ("Beta", "Retail", "Blocked", 500), ("Cato", "Wholesale", "Active", 2500), ("Dune", None, "Active", None)]
    for n, g, s, lim in specs:
        new_doc("Customer", customer_name=n, customer_group=g, status=s, credit_limit=lim).insert()
    mk = lambda cust, d, qty, rate: new_doc("Sales Order", customer=cust, order_date=d, items=[{"description": "w", "qty": qty, "rate": rate}]).insert()
    mk("CUST-0001", "2026-01-10", 2, 100)        # Acme  200
    mk("CUST-0001", "2026-02-20", 1, 50)         # Acme   50
    mk("CUST-0002", "2026-02-25", 4, 25)         # Beta  100
    mk("CUST-0003", "2026-04-05", 10, 30)        # Cato  300
    cancelled = mk("CUST-0003", "2026-04-06", 1, 9999)
    cancelled.submit(); velora.get_doc("Sales Order", cancelled.name).cancel()


def test_script_report_builds_a_hierarchy_with_subtotals_and_a_grand_total(site):
    seed()
    r = run_report("Sales by Customer Group", {"from_date": "2026-01-01", "to_date": "2026-12-31"})
    rows = [(x.type, x.indent, x.values.get("name"), x.values.get("orders"), x.values.get("amount")) for x in r.rows]
    assert rows == [("header", 0, "Retail", None, None), ("data", 1, "CUST-0001", 2, 250.0), ("data", 1, "CUST-0002", 1, 100.0),
                    ("subtotal", 0, "Total Retail", 3.0, 350.0), ("header", 0, "Wholesale", None, None), ("data", 1, "CUST-0003", 1, 300.0),
                    ("subtotal", 0, "Total Wholesale", 1.0, 300.0), ("total", 0, "TOTAL", 4.0, 650.0)]            # the cancelled 9,999 order never counts
    assert r.company == "" and r.subtitle == "1 Jan 2026 to 31 Dec 2026" and r.report_name == "Sales by Customer Group" and r.generated_at.endswith("UTC")
    assert r.filters == []                                                                                          # the period is in the subtitle, not repeated


def test_script_report_filters(site):
    seed()
    r = run_report("Sales by Customer Group", {"from_date": "2026-02-01", "to_date": "2026-03-01"})
    assert r.rows[-1].values["amount"] == 150.0 and r.rows[-1].values["orders"] == 2.0                              # Feb only
    r = run_report("Sales by Customer Group", {"from_date": "2026-01-01", "to_date": "2026-12-31", "customer_group": "Wholesale"})
    assert [x.values.get("name") for x in r.rows if x.type == "data"] == ["CUST-0003"] and r.filters == [("Customer Group", "Wholesale")]
    r = run_report("Sales by Customer Group", {"from_date": "2030-01-01"})
    assert r.rows == []                                                                                             # empty report: no empty total row


def test_summary_report_two_levels_with_subtotals(site):
    seed()
    r = run_report("Credit Exposure by Group")
    assert [c.label for c in r.columns] == ["Customer Group / Status", "Customers", "Credit Limit"]
    got = [(x.type, x.values["label"], x.values.get("m_0"), x.values.get("m_1")) for x in r.rows]
    assert got == [("header", "Retail", None, None), ("data", "Active", 1, 1000.0), ("data", "Blocked", 1, 500.0), ("subtotal", "Total Retail", 2.0, 1500.0),
                   ("header", "Wholesale", None, None), ("data", "Active", 1, 2500.0), ("subtotal", "Total Wholesale", 1.0, 2500.0),
                   ("header", "(none)", None, None), ("data", "Active", 1, None), ("subtotal", "Total (none)", 1.0, None),
                   ("total", "Total", 4.0, 4000.0)]                    # NULL group shown as "(none)" and sorted LAST on every database
    only = run_report("Credit Exposure by Group", {"status": "Active"})
    assert only.rows[-1].values["m_0"] == 3.0 and only.rows[-1].values["m_1"] == 3500.0 and only.filters == [("Status", "Active")]


def test_adhoc_report_on_any_doctype_with_date_buckets(site):
    seed()
    r = run_adhoc({"doctype": "Sales Order", "group_by": ["order_date"], "date_field": "order_date", "date_bucket": "month",
                   "measures": [{"fn": "count", "label": "Orders"}, {"fn": "sum", "field": "total", "label": "Revenue"}], "title": "Revenue by month"})
    got = [(x.values["label"], x.values["m_0"], x.values["m_1"]) for x in r.rows if x.type == "data"]
    assert got == [("2026-01", 1, 200.0), ("2026-02", 2, 150.0), ("2026-04", 1, 300.0)] and r.rows[-1].values["m_1"] == 650.0 and r.title == "Revenue by month"
    q = run_adhoc({"doctype": "Sales Order", "group_by": ["order_date"], "date_field": "order_date", "date_bucket": "quarter", "measures": [{"fn": "count"}]})
    assert [(x.values["label"], x.values["m_0"]) for x in q.rows if x.type == "data"] == [("2026-Q1", 3), ("2026-Q2", 1)]
    y = run_adhoc({"doctype": "Sales Order", "group_by": ["order_date"], "date_field": "order_date", "date_bucket": "year", "measures": [{"fn": "count"}]})
    assert [x.values["label"] for x in y.rows if x.type == "data"] == ["2026"]
    st = run_adhoc({"doctype": "Sales Order", "group_by": ["docstatus"], "measures": [{"fn": "count"}], "filters": [["docstatus", ">=", 0]]})
    assert {x.values["label"] for x in st.rows if x.type == "data"} == {"Draft", "Cancelled"} or {x.values["label"] for x in st.rows if x.type == "data"} == {"Draft"}
    f = run_adhoc({"doctype": "Customer", "group_by": ["status"], "measures": [{"fn": "avg", "field": "credit_limit", "label": "Avg limit"}], "filters": [["customer_group", "=", "Retail"]]})
    assert {x.values["label"]: x.values["m_0"] for x in f.rows if x.type == "data"} == {"Active": 1000.0, "Blocked": 500.0}


def test_adhoc_report_rejects_bad_input_and_respects_permissions(site):
    seed()
    for spec, exc in (({"doctype": "Nope", "group_by": ["a"]}, DoesNotExistError), ({"doctype": "Customer", "group_by": ["nope"]}, ValidationError),
                      ({"doctype": "Customer", "group_by": ["status"], "measures": [{"fn": "sum", "field": "customer_name"}]}, ValidationError),
                      ({"doctype": "Customer", "group_by": []}, ValidationError), ({"doctype": "Customer", "group_by": ["status"], "filters": ["x"]}, ValidationError),
                      ({"doctype": "Customer", "group_by": ["status"], "filters": [["status; drop", "=", 1]]}, ValidationError)):
        with pytest.raises(exc):
            run_adhoc(spec)
    with velora.session_as(velora.Session("nobody", frozenset())):
        with pytest.raises(PermissionDenied):
            run_adhoc({"doctype": "Customer", "group_by": ["status"]})


def test_report_access_control(site):
    seed()
    with velora.session_as(velora.Session("sam", frozenset({"Sales User"}))):
        assert run_report("Sales by Customer Group").rows
        assert run_report("Credit Exposure by Group").rows
    with velora.session_as(velora.Session("nobody", frozenset())):
        with pytest.raises(PermissionDenied):
            run_report("Sales by Customer Group")                       # not in the report's roles
        with pytest.raises(PermissionDenied):
            run_report("Credit Exposure by Group")                      # no read on Customer
    with pytest.raises(DoesNotExistError):
        run_report("Ghost Report")


# ============================ Excel ============================
def sample_result(n_cols=4):
    rb = ReportBuilder("Quarterly Sales Report", cols()[:n_cols] if n_cols <= 4 else cols() + [Column(f"c{i}", f"C{i}", "Int") for i in range(n_cols - 4)], currency="NGN")
    rb.section("Retail"); rb.row({"name": "Acme", "qty": 3, "amt": 1250.5, "pct": .4}); rb.row({"name": "Zenith", "qty": 2, "amt": -300.25, "pct": .1}); rb.subtotal("Total Retail")
    rb.section("Wholesale"); rb.row({"name": "Bola", "qty": 5, "amt": 9800, "pct": .5}); rb.subtotal("Total Wholesale"); rb.total("TOTAL")
    res = rb.build(filters=[("Status", "Active")], summary=[{"label": "Orders", "value": 10, "fieldtype": "Int"}])
    res.company, res.subtitle, res.generated_at = "Velora Technologies", "1 Jan 2026 to 7 Nov 2026", "07 Nov 2026 10:00 UTC"
    return res


def wb_of(res, palette=None, **kw):
    return load_workbook(io.BytesIO(report_to_xlsx(res, palette, **kw)))


def test_excel_layout_is_quickbooks_style():
    wb = wb_of(sample_result(), user="alice")
    ws = wb.active
    assert ws.title == "Quarterly Sales Report"
    assert [ws.cell(r, 1).value for r in range(1, 5)] == ["Velora Technologies", "Quarterly Sales Report", "1 Jan 2026 to 7 Nov 2026   |   Amounts in NGN", "Filters: Status = Active"]
    assert ws["A6"].value == "Orders" and ws["B6"].value == 10                             # summary block
    hdr = next(r for r in range(1, 20) if ws.cell(r, 1).value == "Name")
    assert [ws.cell(hdr, c).value for c in range(1, 5)] == ["Name", "Qty", "Amount", "Share"]
    labels = [(ws.cell(hdr + i, 1).value, ws.cell(hdr + i, 1).alignment.indent) for i in range(1, 9)]
    assert labels == [("Retail", 0), ("Acme", 1), ("Zenith", 1), ("Total Retail", 0), ("Wholesale", 0), ("Bola", 1), ("Total Wholesale", 0), ("TOTAL", 0)]   # indentation = hierarchy
    assert ws.sheet_view.showGridLines is False and ws.freeze_panes == f"A{hdr + 1}"
    assert (ws.page_setup.fitToWidth or 1) == 1 and ws.page_setup.fitToHeight == 0 and ws.sheet_properties.pageSetUpPr.fitToPage   # 1 page wide (1 is the default, so it is omitted)
    assert ws.print_title_rows.replace("$", "") == f"{hdr}:{hdr}" and ws.page_setup.paperSize == 9 and ws.page_setup.orientation == "portrait"
    assert "Page &P of &N" in ws.oddFooter.center.text and "Velora Technologies - Quarterly Sales Report" in ws.oddFooter.left.text
    assert wb.properties.title == "Quarterly Sales Report" and wb.properties.creator == "alice"
    assert ws.sheet_properties.tabColor is not None


def test_excel_uses_real_numbers_dates_and_accounting_formats():
    rb = ReportBuilder("T", [Column("n", "N"), Column("d", "Date", "Date"), Column("a", "Amt", "Currency"), Column("c", "Cnt", "Int"), Column("p", "Pct", "Percent"), Column("k", "OK", "Check")])
    rb.row({"n": "=1+1", "d": date(2026, 3, 9), "a": -1234.5, "c": 7, "p": .256, "k": True})
    rb.row({"n": "+cmd|' /C calc'!A0", "d": None, "a": 0, "c": None, "p": None, "k": False})
    ws = wb_of(rb.build()).active
    hdr = next(r for r in range(1, 10) if ws.cell(r, 1).value == "N")
    r1, r2 = hdr + 1, hdr + 2
    assert ws.cell(r1, 1).value == "=1+1" and ws.cell(r1, 1).data_type == "s"                 # formula injection neutralised: stored as text
    assert ws.cell(r2, 1).data_type == "s"
    assert isinstance(ws.cell(r1, 2).value, datetime) and ws.cell(r1, 2).value.date() == date(2026, 3, 9) and "mmm" in ws.cell(r1, 2).number_format
    assert ws.cell(r1, 3).value == -1234.5 and ws.cell(r1, 3).number_format == '#,##0.00_);(#,##0.00);"-"_)'    # negatives in (parentheses), zero as a dash
    assert ws.cell(r1, 4).value == 7 and ws.cell(r1, 4).number_format.startswith("#,##0_)")
    assert ws.cell(r1, 5).value == pytest.approx(.256) and ws.cell(r1, 5).number_format.startswith("0.0%")
    assert ws.cell(r1, 6).value == "Yes" and ws.cell(r2, 6).value == "No"
    assert ws.cell(r2, 2).value is None and ws.cell(r2, 4).value is None


def test_excel_totals_are_live_formulas_with_cached_values():
    ws = wb_of(sample_result()).active
    f = {c.coordinate: c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")}
    hdr = next(r for r in range(1, 20) if ws.cell(r, 1).value == "Name")
    ret, wh, tot = hdr + 4, hdr + 7, hdr + 8
    assert f[f"B{ret}"] == f"=SUM(B{hdr + 2}:B{hdr + 3})" and f[f"C{ret}"] == f"=SUM(C{hdr + 2}:C{hdr + 3})"
    assert f[f"C{tot}"] == f"=SUM(C{ret},C{wh})"                                           # grand total = the SUBTOTALS
    assert f"D{ret}" not in f and f"D{tot}" not in f                                       # percent columns are not summed
    cached = load_workbook(io.BytesIO(report_to_xlsx(sample_result())), data_only=True).active
    assert cached[f"C{ret}"].value == pytest.approx(950.25) and cached[f"C{tot}"].value == pytest.approx(10750.25)


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_excel_formulas_recalculate_to_the_values_we_cached(tmp_path):
    """Independent proof: LibreOffice recomputes every SUM and must agree with the numbers we wrote."""
    res = sample_result()
    (tmp_path / "r.xlsx").write_bytes(report_to_xlsx(res))
    recalc = "/mnt/skills/public/xlsx/scripts/recalc.py"
    if not os.path.exists(recalc):
        pytest.skip("recalc helper not available")
    out = json.loads(subprocess.run([sys.executable, recalc, str(tmp_path / "r.xlsx")], capture_output=True, text=True, timeout=120).stdout)
    assert out["status"] == "success" and out["total_errors"] == 0 and out["total_formulas"] >= 6
    before = load_workbook(io.BytesIO(report_to_xlsx(res)), data_only=True).active
    after = load_workbook(tmp_path / "r.xlsx", data_only=True).active
    for row in before.iter_rows():
        for c in row:
            if isinstance(c.value, (int, float)):
                assert after[c.coordinate].value == pytest.approx(c.value), c.coordinate


def test_excel_formula_ranges_are_compact_and_correct():
    assert _ranges([5, 6, 7, 9, 12, 13], "C") == "C5:C7,C9,C12:C13" and _ranges([4], "B") == "B4" and _ranges([], "B") == ""
    rb = ReportBuilder("T", [Column("n", "N"), Column("a", "A", "Currency")])
    rb.section("G")
    for i in range(1500):                                                                  # a 1,500-row group is still ONE short formula
        rb.row({"n": f"r{i}", "a": 1})
    rb.subtotal("Total G")
    ws = wb_of(rb.build()).active
    first = next(r for r in range(1, 10) if ws.cell(r, 1).value == "r0")                       # first detail row
    sub = next(c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=SUM"))
    assert sub == f"=SUM(B{first}:B{first + 1499})" and len(sub) < 25


def test_excel_wide_reports_go_landscape_and_freeze_the_label_column():
    ws = wb_of(sample_result(n_cols=9)).active
    assert ws.page_setup.orientation == "landscape"
    hdr = next(r for r in range(1, 20) if ws.cell(r, 1).value == "Name")
    assert ws.freeze_panes == f"B{hdr + 1}"


def test_excel_colours_come_from_the_theme_palette_and_are_soft():
    from velora.theme import compile_theme
    for preset in ("velora", "farepoint", "verdant"):
        pal = compile_theme({"preset": preset}).excel
        ws = wb_of(sample_result(), pal).active
        hdr = next(r for r in range(1, 20) if ws.cell(r, 1).value == "Name")
        assert ws.cell(hdr, 1).fill.fgColor.rgb[-6:].lower() == pal["header_bg"] and ws.cell(hdr, 1).font.color.rgb[-6:].lower() == pal["header_text"]
        assert ws.cell(hdr, 1).font.name == "Arial" and ws.cell(hdr, 1).border.bottom.style == "medium"
        tot = hdr + 8
        assert ws.cell(tot, 1).fill.fgColor.rgb[-6:].lower() == pal["total_bg"] and ws.cell(tot, 1).border.bottom.style == "double"
    assert wb_of(sample_result(), compile_theme({"preset": "farepoint"}).excel).active["A1"].font.color.rgb[-6:] != wb_of(sample_result(), compile_theme({"preset": "verdant"}).excel).active["A1"].font.color.rgb[-6:]


def test_excel_sheet_names_footers_and_limits():
    res = sample_result()
    res.title, res.company = "Profit & Loss / 2026: [draft]?*", "Smith & Sons <Ltd>"
    ws = wb_of(res).active
    assert len(ws.title) <= 31 and not set(ws.title) & set("[]:*?/\\")
    assert "Smith && Sons" in ws.oddFooter.left.text or "Smith & Sons" in ws.oddFooter.left.text
    banded = wb_of(sample_result(), banded=True).active
    assert banded is not None
    big = ReportResult("Big", [Column("n", "N")], [], [])
    big.rows = [None] * (MAX_ROWS + 1)
    with pytest.raises(ValidationError, match="too large"):
        report_to_xlsx(big)


# ============================ API ============================
@pytest.fixture
def client(site):
    return TestClient(create_app(auto_init=False))


def test_report_api_list_run_and_definition(client, site):
    seed()
    lst = client.get("/api/reports", headers=SALES).json()["data"]
    assert {r["name"] for r in lst} == {"Sales by Customer Group", "Credit Exposure by Group"} and all(r["can_export"] for r in lst)
    assert client.get("/api/reports", headers=NOBODY).json()["data"] == []                           # only what you may run
    d = client.get("/api/report/Credit Exposure by Group", headers=SALES).json()["data"]
    assert d["type"] == "summary" and d["filters"][0]["options"] == ["Active", "Inactive", "Blocked"]
    r = client.post("/api/report/Sales by Customer Group/run", json={"filters": {"from_date": "2026-01-01", "to_date": "2026-12-31"}}, headers=SALES)
    body = r.json()["data"]
    assert r.status_code == 200 and body["rows"][-1]["type"] == "total" and body["rows"][-1]["values"]["amount"] == 650.0 and body["columns"][2]["fieldtype"] == "Currency"
    assert client.post("/api/report/Sales by Customer Group/run", json={"filters": {"bogus": 1}}, headers=SALES).status_code == 422
    assert client.post("/api/report/Ghost/run", json={}, headers=SALES).status_code == 404
    assert client.post("/api/report/Sales by Customer Group/run", json={}, headers=NOBODY).status_code == 403
    assert client.post("/api/report/Sales by Customer Group/run", json={}).status_code == 401


def test_report_export_api_is_themed_permissioned_and_audited(client, site):
    seed()
    r = client.put("/api/theme", json={"preset": "farepoint"}, headers=ADMIN)
    assert r.status_code == 200
    r = client.post("/api/report/Sales by Customer Group/export", json={"filters": {"from_date": "2026-01-01", "to_date": "2026-12-31"}}, headers=SALES)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert 'filename="Sales_by_Customer_Group_' in r.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(r.content)).active
    hdr = next(i for i in range(1, 20) if ws.cell(i, 1).value == "Customer")
    from velora.theme import compile_theme
    assert ws.cell(hdr, 1).fill.fgColor.rgb[-6:].lower() == compile_theme({"preset": "farepoint"}).excel["header_bg"]       # the company's theme
    assert str(ws.cell(hdr + 8, 3).value).startswith("=SUM(") and ws["A1"].value == "Sales by Customer Group"          # no company set: the title leads
    with db.transaction() as conn:
        log = conn.execute(select(export_log).where(export_log.c.scope == "report")).mappings().all()
    assert len(log) == 1 and log[0]["owner"] == "sam" and log[0]["detail"]["report"] == "Sales by Customer Group" and log[0]["row_count"] == 3


def test_report_export_requires_the_export_permission(client, site):
    seed()
    sales_only_read = {"X-Velora-User": "r", "X-Velora-Roles": "Sales User"}
    # Customer Group grants Sales User read but NOT export; a report on it must not be exportable even though it can be run
    from velora.meta.registry import Registry  # noqa: F401
    r = client.post("/api/adhoc-report/export", json={"doctype": "Customer Group", "group_by": ["name"], "measures": [{"fn": "count"}]}, headers=sales_only_read)
    assert r.status_code == 403 and "export" in r.json()["message"]
    assert client.post("/api/adhoc-report/run", json={"doctype": "Customer Group", "group_by": ["name"], "measures": [{"fn": "count"}]}, headers=sales_only_read).status_code == 200
    assert client.post("/api/adhoc-report/export", json={"doctype": "Customer Group", "group_by": ["name"], "measures": [{"fn": "count"}]}, headers=ADMIN).status_code == 200


def test_adhoc_report_api(client, site):
    seed()
    spec = {"doctype": "Customer", "group_by": ["customer_group", "status"], "measures": [{"fn": "count", "label": "Customers"}, {"fn": "sum", "field": "credit_limit", "label": "Limit"}], "title": "Customers by group"}
    j = client.post("/api/adhoc-report/run", json=spec, headers=SALES).json()["data"]
    assert j["title"] == "Customers by group" and j["rows"][-1]["values"]["m_1"] == 4000.0
    x = client.post("/api/adhoc-report/export", json=spec, headers=SALES)
    assert x.status_code == 200 and load_workbook(io.BytesIO(x.content)).active["A1"].value == "Customers by group"
    assert client.post("/api/adhoc-report/run", json={**spec, "group_by": ["nope"]}, headers=SALES).status_code == 422


def test_totals_are_exact_decimals_never_float_noise():
    """Regression: totals were summed as floats, so 0.1 + 0.2 appeared as 0.30000000000000004 (and a trial balance's debits and credits differed by 1e-11)."""
    from decimal import Decimal as Dc
    rb = ReportBuilder("T", [Column("name", "Name"), Column("amount", "Amount", "Currency")])
    for v in (0.1, 0.2, Dc("0.3"), 1, "x" and 0.7):
        rb.row({"name": "r", "amount": v})
    rb.total("Total")
    top = rb.build().to_dict()["rows"][-1]["values"]["amount"]
    assert top == 2.3 and repr(top) == "2.3"
    big = ReportBuilder("T", [Column("name", "Name"), Column("amount", "Amount", "Currency")])
    for _ in range(1000):
        big.row({"name": "r", "amount": Dc("143.21")})
    big.total("Total")
    assert big.build().to_dict()["rows"][-1]["values"]["amount"] == 143210.0
    three = ReportBuilder("T", [Column("name", "Name"), Column("amount", "Amount", "Currency")])
    for _ in range(3):
        three.row({"name": "r", "amount": 0.1})
    three.total("Total")
    got = three.build().to_dict()["rows"][-1]["values"]["amount"]
    assert got == 0.3 and repr(got) == "0.3"                                           # float arithmetic gives 0.30000000000000004 here


def test_excel_export_writes_decimal_values_and_totals_as_real_numbers():
    """Regression: the Excel writer only knew int/float, so exact Decimal values (every accounting report) came out as blank cells."""
    import io
    from decimal import Decimal as Dc
    from openpyxl import load_workbook
    from velora.reporting.excel import report_to_xlsx
    rb = ReportBuilder("Decimal report", [Column("name", "Name"), Column("amount", "Amount", "Currency")])
    rb.section("A")
    rb.row({"name": "x", "amount": Dc("1200.10")})
    rb.row({"name": "y", "amount": Dc("0.20")})
    rb.subtotal("Total A")
    rb.total("Grand total")
    ws = load_workbook(io.BytesIO(report_to_xlsx(rb.build())), data_only=True).active                # cached values, as Excel/LibreOffice show them
    nums = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, (int, float)) and not isinstance(c.value, bool)]
    assert 1200.10 in nums and 0.20 in nums and nums.count(1200.30) >= 2                       # data cells AND the (cached) subtotal/total values are numbers
    wb2 = load_workbook(io.BytesIO(report_to_xlsx(rb.build())), data_only=False).active
    assert any(isinstance(c.value, str) and c.value.startswith("=SUM(") for row in wb2.iter_rows() for c in row)       # and the formulas are still real


def test_saved_report_revisions_are_immutable_and_restore_as_new_version(site):
    from velora.reporting.saved import create_saved, update_saved, list_versions, restore_version
    from velora.permissions import session_as, Session
    from velora import registry
    # Use a DocType and valid adhoc definition already available in the demo registry.
    spec = {"doctype":"Customer", "group_by":["status"], "measures":[{"fn":"count"}], "filters":[]}
    with session_as(Session("report-owner", frozenset({"System Manager"}))):
        saved = create_saved("Revision test", spec, False)
        first = list_versions(saved["id"])
        assert len(first) == 1 and first[0]["version"] == 1
        changed = dict(spec, title="Second revision")
        update_saved(saved["id"], spec=changed)
        versions = list_versions(saved["id"])
        assert [v["version"] for v in versions] == [2, 1]
        restored = restore_version(saved["id"], 1)
        assert restored["spec"].get("title") is None
        versions = list_versions(saved["id"])
        assert [v["version"] for v in versions] == [3, 2, 1]
