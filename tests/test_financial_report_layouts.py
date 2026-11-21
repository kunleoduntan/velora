import pytest
from velora.exceptions import ValidationError
from velora.reporting.layouts import validate_definition, calculate


def sample():
    return {
        "rows": [
            {"code": "SALES", "description": "Sales", "type": "account_range", "from_account": "4000", "to_account": "4999", "sign": 1, "bold": True},
            {"code": "COST", "description": "Cost of sales", "type": "account", "account_no": "5000", "sign": -1},
            {"code": "GROSS_PROFIT", "description": "Gross profit", "type": "formula", "formula": "[SALES]+[COST]", "bold": True},
        ],
        "columns": [
            {"code": "ACTUAL", "caption": "Current period", "type": "net_change", "period": "month"},
            {"code": "PRIOR", "caption": "Prior year", "type": "same_period_last_year", "period": "month", "offset": -12},
            {"code": "VARIANCE", "caption": "Variance", "type": "formula", "formula": "[ACTUAL]-[PRIOR]"},
        ]
    }


def test_validates_and_normalizes_row_and_column_definitions():
    spec = validate_definition(sample())
    assert spec["rows"][0]["type"] == "account_range"
    assert spec["columns"][1]["offset"] == -12
    assert spec["rows"][0]["bold"] is True


def test_calculates_account_rows_and_row_formulas():
    definition = sample()
    # The balances adapter provides a company- and permission-scoped account balance matrix.
    balances = {
        ("4100", "ACTUAL"): 1200, ("4500", "ACTUAL"): 300,
        ("5000", "ACTUAL"): 700, ("4100", "PRIOR"): 1000,
        ("5000", "PRIOR"): 600,
    }
    result = calculate(definition, balances, {"ACTUAL": "Nov 2026", "PRIOR": "Nov 2025", "VARIANCE": "Variance"})
    rows = {r["code"]: r for r in result["rows"]}
    assert rows["SALES"]["values"]["ACTUAL"] == 1500
    assert rows["COST"]["values"]["ACTUAL"] == -700
    assert rows["GROSS_PROFIT"]["values"]["ACTUAL"] == 800
    assert rows["GROSS_PROFIT"]["values"]["PRIOR"] == 400
    assert rows["GROSS_PROFIT"]["values"]["VARIANCE"] == 400


@pytest.mark.parametrize("bad", [
    {"rows": [], "columns": [{"code": "A"}]},
    {"rows": [{"code": "A", "type": "unknown"}], "columns": [{"code": "C"}]},
    {"rows": [{"code": "A", "type": "account"}], "columns": [{"code": "C"}]},
    {"rows": [{"code": "A", "type": "formula", "formula": "[MISSING]+1"}], "columns": [{"code": "C"}]},
    {"rows": [{"code": "A", "type": "text"}], "columns": [{"code": "C", "type": "formula", "formula": "[MISSING]+1"}]},
])
def test_rejects_invalid_layout_definitions(bad):
    with pytest.raises(ValidationError):
        validate_definition(bad)


def test_rejects_formula_code_injection():
    spec = sample()
    spec["rows"][2]["formula"] = "__import__('os').system('id')"
    with pytest.raises(ValidationError):
        validate_definition(spec)


def test_rejects_forward_column_formula_reference():
    spec = sample()
    spec["columns"][0] = {"code": "ACTUAL", "type": "formula", "formula": "[PRIOR]+1"}
    with pytest.raises(ValidationError):
        validate_definition(spec)


def test_calculates_account_category_and_dimension_rows_from_adapter_metadata():
    definition = {
        "rows": [
            {"code": "BANKS", "type": "account_category", "category": "Bank", "description": "Bank accounts"},
            {"code": "LAGOS", "type": "dimension", "dimension": "branch", "dimension_value": "Lagos", "description": "Lagos"},
        ],
        "columns": [{"code": "ACTUAL", "type": "net_change"}],
    }
    balances = {("1001", "ACTUAL"): 100, ("1002", "ACTUAL"): 250, ("1003", "ACTUAL"): 75}
    attrs = {
        "1001": {"category": "Bank", "dimensions": {"branch": "Lagos"}},
        "1002": {"category": "Bank", "dimensions": {"branch": "Abuja"}},
        "1003": {"category": "Cash", "dimensions": {"branch": "Lagos"}},
    }
    rows = {r["code"]: r for r in calculate(definition, balances, {}, attrs)["rows"]}
    assert rows["BANKS"]["values"]["ACTUAL"] == 350
    assert rows["LAGOS"]["values"]["ACTUAL"] == 175


def test_budget_column_and_actual_vs_budget_formula():
    definition = {
        "rows": [{"code": "INCOME", "type": "account_range", "from_account": "4000", "to_account": "4999"}],
        "columns": [
            {"code": "ACTUAL", "type": "net_change"},
            {"code": "BUDGET", "type": "budget"},
            {"code": "VARIANCE", "type": "formula", "formula": "[ACTUAL]-[BUDGET]"},
        ],
    }
    result = calculate(definition, {("4100", "ACTUAL"): 1250, ("4100", "BUDGET"): 1000}, {})
    assert result["rows"][0]["values"] == {"ACTUAL": 1250.0, "BUDGET": 1000.0, "VARIANCE": 250.0}



def test_financial_period_resolution_preserves_selected_date_range():
    from datetime import date
    from velora.reporting.layouts import _period_bounds
    filters = {"from_date": "2026-11-03", "to_date": "2026-11-13", "as_of_date": "2026-11-13"}
    assert _period_bounds({"type": "net_change", "date_mode": "current_period", "period": "month", "offset": 0}, filters) == (date(2026, 11, 3), date(2026, 11, 13))
    assert _period_bounds({"type": "same_period_last_year", "date_mode": "current_period", "period": "month", "offset": -12}, filters) == (date(2025, 11, 3), date(2025, 11, 13))
    assert _period_bounds({"type": "year_to_date", "date_mode": "current_period", "period": "year", "offset": 0}, filters) == (date(2026, 1, 1), date(2026, 11, 13))



def test_financial_statement_xlsx_is_a_valid_workbook():
    import io, zipfile
    from velora.reporting.layouts import financial_statement_xlsx
    content = financial_statement_xlsx({
        "name": "Profit & Loss",
        "filters": {"from_date": "2026-11-01", "to_date": "2026-11-30"},
        "columns": [{"code": "ACTUAL", "caption": "Actual", "period_label": "Nov 2026"}],
        "rows": [{"code": "SALES", "description": "=HYPERLINK(\"https://example.com\")", "bold": True, "indent": 0, "values": {"ACTUAL": 123.45}}],
    })
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.testzip() is None
        assert "xl/worksheets/sheet1.xml" in archive.namelist()


def test_opening_balance_column_resolves_to_day_before_period_start():
    from datetime import date
    from velora.reporting.layouts import _period_bounds
    filters = {"from_date": "2026-11-01", "to_date": "2026-11-30"}
    assert _period_bounds({"type": "opening_balance", "date_mode": "current_period", "period": "day", "offset": 0}, filters) == (date(2026, 10, 31), date(2026, 10, 31))


def test_as_of_columns_support_prior_year_comparatives():
    from datetime import date
    from velora.reporting.layouts import _period_bounds
    filters = {"as_of_date": "2026-11-15"}
    assert _period_bounds({"type": "balance_at_date", "date_mode": "as_of", "period": "year", "offset": -1}, filters) == (date(2025, 1, 1), date(2025, 11, 15))
