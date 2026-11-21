from decimal import Decimal
import pytest

from velora_erp.finance.tax_engine import (
    PayrollTaxError, progressive_tax, calculate_period_tax,
    calculate_ytd_tax_adjustment,
)

BANDS = [
    {"lower_limit": 0, "upper_limit": 1000, "rate": 10},
    {"lower_limit": 1000, "upper_limit": 3000, "rate": 20},
    {"lower_limit": 3000, "upper_limit": None, "rate": 30},
]


def test_progressive_tax_boundary_and_relief_rounding():
    assert progressive_tax("1000", BANDS) == Decimal("100.00")
    assert progressive_tax("3000", BANDS) == Decimal("500.00")
    assert progressive_tax("4000", BANDS, relief="500") == Decimal("650.00")
    assert progressive_tax("1.005", [{"lower_limit": 0, "upper_limit": None, "rate": 100}]) == Decimal("1.01")


@pytest.mark.parametrize("bands", [
    [{"lower_limit": 1, "upper_limit": None, "rate": 10}],
    [{"lower_limit": 0, "upper_limit": 100, "rate": 10}],
    [{"lower_limit": 0, "upper_limit": 100, "rate": 10}, {"lower_limit": 101, "upper_limit": None, "rate": 20}],
    [{"lower_limit": 0, "upper_limit": None, "rate": 10}, {"lower_limit": 100, "upper_limit": None, "rate": 20}],
    [{"lower_limit": 0, "upper_limit": None, "rate": 101}],
])
def test_invalid_tax_band_structures_are_rejected(bands):
    with pytest.raises(PayrollTaxError):
        progressive_tax(100, bands)


def test_tax_engine_rejects_nan_infinity_and_invalid_precision():
    with pytest.raises(PayrollTaxError):
        progressive_tax("NaN", BANDS)
    with pytest.raises(PayrollTaxError):
        progressive_tax("Infinity", BANDS)
    with pytest.raises(PayrollTaxError):
        progressive_tax(100, BANDS, precision=-1)


def test_ytd_tax_adjustment_reports_cumulative_true_up_and_refund_review():
    result = calculate_ytd_tax_adjustment(
        ytd_taxable_income=6000, prior_tax_withheld=1650,
        remaining_periods=6, periods_per_year=12, bands=BANDS,
    )
    assert result["periods_elapsed"] == 6
    assert result["projected_annual_taxable_income"] == Decimal("12000")
    assert result["current_period_adjustment"] == Decimal("-50.00")
    assert result["requires_refund_or_credit_review"] is True


def test_ytd_tax_adjustment_rejects_inconsistent_period_counts():
    with pytest.raises(PayrollTaxError):
        calculate_ytd_tax_adjustment(ytd_taxable_income=100, prior_tax_withheld=0,
            remaining_periods=12, periods_per_year=12, bands=BANDS)
