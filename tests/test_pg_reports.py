"""Reporting power from PostgreSQL: true subtotals via ROLLUP, percentiles/median/stddev, distinct counts, per-measure FILTER, and gap-filled time series."""
import io
from datetime import date

import pytest
from openpyxl import load_workbook

from velora import new_doc
from velora.db import get_engine
from velora.exceptions import ValidationError
from velora.reporting.definition import ReportDef
from velora.reporting.excel import report_to_xlsx
from velora.reporting.runner import run_adhoc
from velora.reporting.summary import _periods


def pg():
    return get_engine().dialect.name == "postgresql"


def seed():
    for g in ("Retail", "Wholesale"):
        new_doc("Customer Group", group_name=g).insert()
    rows = [("A", "Retail", "Active", 100), ("B", "Retail", "Active", 200), ("C", "Retail", "Blocked", 300), ("D", "Wholesale", "Active", 1000), ("E", "Wholesale", "Active", 2000),
            ("F", "Wholesale", "Blocked", 9000), ("G", "Wholesale", "Active", 3000)]
    for n, g, s, lim in rows:
        new_doc("Customer", customer_name=n, customer_group=g, status=s, credit_limit=lim).insert()


def run(**kw):
    spec = {"doctype": "Customer", "group_by": ["customer_group"], "measures": [{"fn": "count", "label": "Customers"}], **kw}
    return run_adhoc(spec)


def vals(res, kinds=("data",)):
    return [(r.values["label"], *[r.values.get(f"m_{i}") for i in range(len(res.columns) - 1)]) for r in res.rows if r.type in kinds]


# ============================== portable additions (SQLite and PostgreSQL) ==============================
def test_distinct_counts_and_per_measure_filters(site):
    seed()
    r = run(measures=[{"fn": "count", "label": "All"}, {"fn": "count", "label": "Active", "where": [["status", "=", "Active"]]},
                      {"fn": "sum", "field": "credit_limit", "label": "Blocked limit", "where": [["status", "=", "Blocked"]]}, {"fn": "count_distinct", "field": "status", "label": "Statuses"}])
    d = {x[0]: x[1:] for x in vals(r)}
    assert d["Retail"] == (3, 2, 300, 2) and d["Wholesale"] == (4, 3, 9000, 2)                                          # one query, four different slices of the same rows
    assert [x.values for x in r.rows if x.type == "total"][0]["m_0"] == 7 and [x.values for x in r.rows if x.type == "total"][0]["m_1"] == 5 and [x.values for x in r.rows if x.type == "total"][0]["m_2"] == 9300


def test_a_filter_with_an_unknown_field_or_operator_is_refused(site):
    seed()
    for bad in ([["nope", "=", 1]], [["status", "~", "x"]], [["status"]], "x"):
        with pytest.raises(ValidationError):
            run(measures=[{"fn": "count", "where": bad}])


@pytest.mark.parametrize("bucket,first,last,expected", [
    ("month", "2026-01", "2026-04", ["2026-01", "2026-02", "2026-03", "2026-04"]), ("month", "2025-11", "2026-02", ["2025-11", "2025-12", "2026-01", "2026-02"]),
    ("quarter", "2025-Q3", "2026-Q2", ["2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2"]), ("year", "2024", "2027", ["2024", "2025", "2026", "2027"]),
    ("day", "2026-02-27", "2026-03-02", ["2026-02-27", "2026-02-28", "2026-03-01", "2026-03-02"]), ("day", "2028-02-28", "2028-03-01", ["2028-02-28", "2028-02-29", "2028-03-01"]),
    ("month", "2026-05", "2026-05", ["2026-05"])])
def test_period_sequences_are_complete_across_year_ends_and_leap_days(bucket, first, last, expected):
    assert _periods(first, last, bucket) == expected


def test_gap_fill_shows_every_month_with_zeros_for_the_empty_ones(site):
    for d, n in ((date(2026, 1, 5), "A"), (date(2026, 1, 9), "B"), (date(2026, 4, 2), "C")):
        c = new_doc("Customer", customer_name=n, credit_limit=10).insert()
        so = new_doc("Sales Order", customer=c.name, order_date=d)
        so.append("items", {"description": n, "qty": 1, "rate": 100})
        so.insert()
    spec = {"doctype": "Sales Order", "group_by": ["order_date"], "date_field": "order_date", "date_bucket": "month", "measures": [{"fn": "count", "label": "Orders"}, {"fn": "avg", "field": "total", "label": "Average"}]}
    plain = run_adhoc(spec)
    assert [x[0] for x in vals(plain)] == ["2026-01", "2026-04"]
    filled = run_adhoc({**spec, "gap_fill": True})
    assert vals(filled) == [("2026-01", 2, 100.0), ("2026-02", 0, None), ("2026-03", 0, None), ("2026-04", 1, 100.0)]        # a gap is a zero count, an unknown average is blank - never invented
    assert [x.values["m_0"] for x in filled.rows if x.type == "total"] == [3]
    with pytest.raises(ValidationError, match="gap_fill needs the date field as the ONLY group_by"):
        run_adhoc({**spec, "group_by": ["customer"], "gap_fill": True})
    with pytest.raises(ValidationError, match="gap_fill must be true or false"):
        run_adhoc({**spec, "gap_fill": "yes"})


def test_report_definitions_validate_the_new_options():
    base = {"name": "R", "type": "summary", "ref_doctype": "Customer", "group_by": ["customer_group"], "measures": [{"fn": "count"}]}
    assert ReportDef.from_dict({**base, "measures": [{"fn": "percentile", "field": "credit_limit", "p": 90}, {"fn": "median", "field": "credit_limit"}, {"fn": "stddev", "field": "credit_limit"}]}, "t", "t").measures
    for m, frag in (({"fn": "percentile", "field": "credit_limit"}, "needs p between 0 and 100"), ({"fn": "percentile", "field": "credit_limit", "p": 100}, "needs p between 0 and 100"),
                    ({"fn": "percentile", "field": "credit_limit", "p": True}, "needs p between 0 and 100"), ({"fn": "median"}, "median needs a field"), ({"fn": "count", "where": "x"}, "'where' must be a list"),
                    ({"fn": "count", "where": [["a", "=", 1], ["b"]]}, "'where' must be a list")):
        with pytest.raises(Exception, match=frag):
            ReportDef.from_dict({**base, "measures": [m]}, "t", "t")


# ============================== PostgreSQL-only: aggregates SQLite does not have ==============================
def test_median_percentile_and_stddev(site):
    seed()
    if not pg():
        for fn in ("median", "percentile", "stddev"):
            with pytest.raises(ValidationError, match=f"'{fn}' measure needs PostgreSQL"):
                run(measures=[{"fn": fn, "field": "credit_limit", "p": 90}])
        return
    r = run(measures=[{"fn": "median", "field": "credit_limit", "label": "Median"}, {"fn": "percentile", "field": "credit_limit", "p": 90, "label": "P90"},
                      {"fn": "stddev", "field": "credit_limit", "label": "Std dev"}, {"fn": "avg", "field": "credit_limit", "label": "Mean"}])
    d = {x[0]: x[1:] for x in vals(r)}
    assert d["Retail"][0] == 200 and d["Wholesale"][0] == 2500                                                          # the median is NOT the mean: Wholesale's mean is 3750, dragged by one 9000
    assert d["Wholesale"][3] == 3750 and round(d["Retail"][2], 2) == 100.0 and round(d["Retail"][1], 1) == 280.0       # P90 of 100,200,300 interpolates to 280
    assert r.columns[1].label == "Median of Credit Limit" or "Median" in r.columns[1].label


# ============================== PostgreSQL-only: ROLLUP gives TRUE subtotals ==============================
def test_rollup_computes_real_subtotals_and_grand_totals_for_averages_and_medians(site):
    seed()
    spec = {"doctype": "Customer", "group_by": ["customer_group", "status"], "rollup": True,
            "measures": [{"fn": "count", "label": "Customers"}, {"fn": "sum", "field": "credit_limit", "label": "Total limit"}, {"fn": "avg", "field": "credit_limit", "label": "Average"},
                         {"fn": "median", "field": "credit_limit", "label": "Median"}, {"fn": "max", "field": "credit_limit", "label": "Largest"}]}
    if not pg():
        with pytest.raises(ValidationError, match="'rollup' needs PostgreSQL|measure needs PostgreSQL"):
            run_adhoc(spec)
        return
    res = run_adhoc(spec)
    sub = {r.values["label"]: r.values for r in res.rows if r.type == "subtotal"}
    tot = next(r.values for r in res.rows if r.type == "total")
    assert sub["Total Retail"]["m_0"] == 3 and sub["Total Retail"]["m_1"] == 600 and sub["Total Retail"]["m_2"] == 200 and sub["Total Retail"]["m_3"] == 200 and sub["Total Retail"]["m_4"] == 300
    assert sub["Total Wholesale"]["m_2"] == 3750 and sub["Total Wholesale"]["m_3"] == 2500 and sub["Total Wholesale"]["m_4"] == 9000
    assert tot["m_0"] == 7 and tot["m_1"] == 15600 and round(tot["m_2"], 2) == round(15600 / 7, 2) and tot["m_3"] == 1000 and tot["m_4"] == 9000          # the grand median is of all 7, not of the subtotals
    assert [r.type for r in res.rows].count("data") == 4 and res.rows[-1].type == "total"
    one = run_adhoc({**spec, "group_by": ["customer_group"]})
    assert [r.type for r in one.rows] == ["data", "data", "total"] and one.rows[-1].values["m_3"] == 1000


def test_rollup_totals_survive_an_excel_export_with_real_formulas_and_database_values(site):
    if not pg():
        pytest.skip("PostgreSQL only")
    seed()
    res = run_adhoc({"doctype": "Customer", "group_by": ["customer_group", "status"], "rollup": True, "title": "Rollup",
                     "measures": [{"fn": "sum", "field": "credit_limit", "label": "Total limit"}, {"fn": "median", "field": "credit_limit", "label": "Median"}]})
    ws = load_workbook(io.BytesIO(report_to_xlsx(res)), data_only=True).active
    cached = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, (int, float))]
    assert 15600 in cached and 1000 in cached and 2500 in cached                                                         # the grand total, the true grand median, a true subtotal median
    f = load_workbook(io.BytesIO(report_to_xlsx(res))).active
    assert any(isinstance(c.value, str) and c.value.startswith("=SUM(") for row in f.iter_rows() for c in row)           # additive columns are still live formulas


def test_rollup_with_a_null_group_keeps_it_apart_from_the_subtotal(site):
    if not pg():
        pytest.skip("PostgreSQL only")
    new_doc("Customer", customer_name="NoGroup", credit_limit=50).insert()
    new_doc("Customer Group", group_name="Retail").insert()
    new_doc("Customer", customer_name="R1", customer_group="Retail", credit_limit=10).insert()
    res = run_adhoc({"doctype": "Customer", "group_by": ["customer_group"], "rollup": True, "measures": [{"fn": "sum", "field": "credit_limit"}]})
    assert [(r.type, r.values["label"], r.values["m_0"]) for r in res.rows] == [("data", "Retail", 10), ("data", "(none)", 50), ("total", "Total", 60)]       # a real NULL group is data, not the grand total


def test_which_fields_each_measure_accepts(site):
    seed()
    assert run(measures=[{"fn": "count_distinct", "field": "status"}])                                                  # any column can be counted
    assert run(measures=[{"fn": "max", "field": "credit_limit"}])
    for fn, field in (("sum", "status"), ("avg", "customer_name"), ("sum", "nope"), ("count_distinct", "nope")):
        with pytest.raises(ValidationError, match="Invalid field"):
            run(measures=[{"fn": fn, "field": field}])
    c = new_doc("Customer", customer_name="X").insert()
    for d in (date(2026, 1, 5), date(2026, 3, 9)):
        so = new_doc("Sales Order", customer=c.name, order_date=d)
        so.append("items", {"description": "a", "qty": 1, "rate": 1})
        so.insert()
    latest = run_adhoc({"doctype": "Sales Order", "group_by": ["customer"], "measures": [{"fn": "max", "field": "order_date", "label": "Latest"}, {"fn": "min", "field": "order_date", "label": "First"}]})
    assert vals(latest)[0][1:] == (date(2026, 3, 9), date(2026, 1, 5))                                                   # a date is a valid thing to take the latest/earliest of
