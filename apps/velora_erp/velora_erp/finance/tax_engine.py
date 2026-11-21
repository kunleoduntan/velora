"""Jurisdiction-neutral, deterministic payroll tax calculation primitives.

Tax rates and thresholds are configuration supplied by a jurisdiction. This
module deliberately contains no hard-coded statutory rates.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class PayrollTaxError(ValueError):
    """Raised when tax inputs or configured tax bands are invalid."""


def _amount(value, label, *, non_negative=True):
    try:
        result = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        raise PayrollTaxError(f"{label} must be a valid decimal amount") from None
    if not result.is_finite() or (non_negative and result < 0):
        qualifier = "finite and non-negative" if non_negative else "finite"
        raise PayrollTaxError(f"{label} must be {qualifier}")
    return result


def _precision(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 8:
        raise PayrollTaxError("Currency precision must be an integer between 0 and 8")
    return value


def validate_tax_bands(bands):
    """Validate a complete progressive schedule starting at zero.

    Bands must be contiguous, non-overlapping, ordered by lower limit, and
    terminate in exactly one open-ended band. Rates are percentages.
    """
    if not isinstance(bands, (list, tuple)) or not bands:
        raise PayrollTaxError("At least one tax band is required")
    parsed = []
    for index, band in enumerate(bands, 1):
        if not isinstance(band, dict):
            raise PayrollTaxError(f"Tax band {index} must be an object")
        lower = _amount(band.get("lower_limit", 0), f"Tax band {index} lower limit")
        upper_raw = band.get("upper_limit")
        upper = None if upper_raw in (None, "") else _amount(upper_raw, f"Tax band {index} upper limit")
        rate = _amount(band.get("rate", 0), f"Tax band {index} rate")
        if rate > 100:
            raise PayrollTaxError(f"Tax band {index} rate cannot exceed 100 percent")
        if upper is not None and upper <= lower:
            raise PayrollTaxError(f"Tax band {index} upper limit must exceed its lower limit")
        parsed.append({"lower_limit": lower, "upper_limit": upper, "rate": rate})
    if parsed[0]["lower_limit"] != 0:
        raise PayrollTaxError("The first tax band must start at zero")
    for index, band in enumerate(parsed):
        if band["upper_limit"] is None and index != len(parsed) - 1:
            raise PayrollTaxError("Only the final tax band may be open-ended")
        if index:
            previous = parsed[index - 1]["upper_limit"]
            if previous is None or band["lower_limit"] != previous:
                raise PayrollTaxError("Tax bands must be contiguous and non-overlapping")
    if parsed[-1]["upper_limit"] is not None:
        raise PayrollTaxError("The final tax band must be open-ended")
    return parsed


def progressive_tax(taxable_income, bands, *, relief=0, precision=2):
    precision = _precision(precision)
    income = _amount(taxable_income, "Taxable income")
    relief = _amount(relief, "Tax relief")
    income = max(Decimal(0), income - relief)
    schedule = validate_tax_bands(bands)
    total = Decimal(0)
    for band in schedule:
        lower, upper, rate = band["lower_limit"], band["upper_limit"], band["rate"] / Decimal(100)
        if income <= lower:
            break
        taxable = income - lower if upper is None else min(income, upper) - lower
        if taxable > 0:
            total += taxable * rate
        if upper is None or income <= upper:
            break
    quantum = Decimal(1).scaleb(-precision)
    return total.quantize(quantum, rounding=ROUND_HALF_UP)


def calculate_period_tax(*, period_taxable_income, periods_per_year, bands, annual_relief=0,
                          precision=2, calculation_basis="Annualised Period Income"):
    precision = _precision(precision)
    if isinstance(periods_per_year, bool):
        raise PayrollTaxError("Periods per year must be a positive integer")
    try:
        periods = int(periods_per_year)
    except (TypeError, ValueError):
        raise PayrollTaxError("Periods per year must be a positive integer") from None
    if periods <= 0 or Decimal(str(periods_per_year)) != Decimal(periods):
        raise PayrollTaxError("Periods per year must be a positive integer")
    period_income = _amount(period_taxable_income, "Period taxable income")
    relief = _amount(annual_relief, "Annual tax relief")
    annual = period_income * periods
    quantum = Decimal(1).scaleb(-precision)
    if calculation_basis == "Period Taxable Income":
        period_relief = relief / periods
        period_tax = progressive_tax(period_income, bands, relief=period_relief, precision=precision)
        annual_tax = (period_tax * periods).quantize(quantum, rounding=ROUND_HALF_UP)
    elif calculation_basis == "Annualised Period Income":
        annual_tax = progressive_tax(annual, bands, relief=relief, precision=precision)
        period_tax = (annual_tax / periods).quantize(quantum, rounding=ROUND_HALF_UP)
    else:
        raise PayrollTaxError("Unsupported payroll tax calculation basis")
    return {"annualised_taxable_income": annual, "annual_tax": annual_tax, "period_tax": period_tax}


def calculate_ytd_tax_adjustment(*, ytd_taxable_income, prior_tax_withheld, remaining_periods,
                                 periods_per_year, bands, annual_relief=0, precision=2):
    """Calculate a transparent cumulative annualised PAYE true-up.

    The caller supplies cumulative taxable income and tax already withheld in
    the current tax year. A negative adjustment is returned when prior
    withholding exceeds projected annual liability; payment/refund handling
    remains a separate approved payroll/accounting process.
    """
    precision = _precision(precision)
    ytd_income = _amount(ytd_taxable_income, "YTD taxable income")
    withheld = _amount(prior_tax_withheld, "Prior tax withheld")
    if isinstance(remaining_periods, bool) or isinstance(periods_per_year, bool):
        raise PayrollTaxError("Payroll period counts must be positive integers")
    try:
        remaining = int(remaining_periods)
        total_periods = int(periods_per_year)
    except (TypeError, ValueError):
        raise PayrollTaxError("Payroll period counts must be positive integers") from None
    if remaining < 0 or total_periods <= 0 or remaining + 1 > total_periods:
        raise PayrollTaxError("Remaining periods and periods per year are inconsistent")
    periods_elapsed = total_periods - remaining
    if periods_elapsed <= 0:
        raise PayrollTaxError("At least one payroll period must have elapsed")
    average_period_income = ytd_income / periods_elapsed
    projected_annual_income = average_period_income * total_periods
    annual_liability = progressive_tax(projected_annual_income, bands, relief=annual_relief, precision=precision)
    quantum = Decimal(1).scaleb(-precision)
    cumulative_target = (annual_liability * Decimal(periods_elapsed) / Decimal(total_periods)).quantize(quantum, rounding=ROUND_HALF_UP)
    adjustment = (cumulative_target - withheld).quantize(quantum, rounding=ROUND_HALF_UP)
    return {
        "periods_elapsed": periods_elapsed,
        "remaining_periods": remaining,
        "projected_annual_taxable_income": projected_annual_income,
        "projected_annual_tax_liability": annual_liability,
        "cumulative_tax_target": cumulative_target,
        "prior_tax_withheld": withheld,
        "current_period_adjustment": adjustment,
        "requires_refund_or_credit_review": adjustment < 0,
    }
