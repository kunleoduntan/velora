"""Deterministic, configuration-driven tax calculator (pure functions; no database).

Derived from the standalone `velora_tax_management` foundation, with these corrections:
- inclusive tax: the taxable amount is the gross less the *rounded* tax, so taxable + tax always equals the gross;
- credit notes: a negative base gives a negative tax of the same magnitude (the foundation returned zero for tiered rules);
- tiers are explicit contiguous bands (lower, upper or open-ended, rate); the foundation silently taxed any excess at the last rate;
- tiered rules cannot be inclusive (ambiguous) and fixed rules need a non-zero base;
- rounding precision is a rule setting, not a fixed two places (some currencies have none);
- rates and recoverability are validated to 0..100.
No statutory rate or category is built in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

ZERO, HUNDRED = Decimal("0"), Decimal("100")
METHODS = ("percentage", "fixed", "tiered")


class TaxConfigError(ValueError):
    """The tax configuration is invalid, missing or ambiguous."""


def D(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def quantize(value: Decimal, precision: int = 2) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Rule:
    code: str
    tax_type: str
    jurisdiction: str
    method: str = "percentage"
    rate: Decimal = ZERO
    fixed_amount: Decimal = ZERO
    category: Optional[str] = None
    effective_from: date = date.min
    effective_to: Optional[date] = None
    inclusive: bool = False
    recoverability_percent: Decimal = HUNDRED
    precision: int = 2
    tiers: tuple = ()           # ((lower, upper|None, rate), ...)
    name: str = ""

    def applies_on(self, d: date) -> bool:
        return self.effective_from <= d and (self.effective_to is None or d <= self.effective_to)


@dataclass(frozen=True)
class Result:
    rule_code: str
    tax_type: str
    jurisdiction: str
    taxable_amount: Decimal
    tax_amount: Decimal
    recoverable_amount: Decimal
    non_recoverable_amount: Decimal
    rate: Decimal
    trace: tuple = field(default_factory=tuple)


def validate_rule(r: Rule) -> None:
    if r.method not in METHODS:
        raise TaxConfigError(f"Unsupported method '{r.method}'.")
    if not 0 <= r.precision <= 8:
        raise TaxConfigError("Rounding precision must be between 0 and 8.")
    if not ZERO <= r.recoverability_percent <= HUNDRED:
        raise TaxConfigError("Recoverability must be between 0 and 100 percent.")
    if r.effective_to is not None and r.effective_to < r.effective_from:
        raise TaxConfigError("Effective To cannot be before Effective From.")
    if r.method == "percentage" and not ZERO <= r.rate <= HUNDRED:
        raise TaxConfigError("A percentage rate must be between 0 and 100.")
    if r.method == "fixed" and r.fixed_amount < 0:
        raise TaxConfigError("A fixed tax amount cannot be negative.")
    if r.method == "tiered":
        if r.inclusive:
            raise TaxConfigError("A tiered rule cannot be tax-inclusive.")
        if not r.tiers:
            raise TaxConfigError("A tiered rule needs at least one band.")
        expect = ZERO
        for i, (lo, hi, rate) in enumerate(r.tiers):
            if lo != expect:
                raise TaxConfigError(f"Band {i + 1} must start where the previous band ends ({expect}).")
            if not ZERO <= rate <= HUNDRED:
                raise TaxConfigError(f"Band {i + 1} rate must be between 0 and 100.")
            if hi is None:
                if i != len(r.tiers) - 1:
                    raise TaxConfigError("Only the last band may be open-ended.")
            else:
                if hi <= lo:
                    raise TaxConfigError(f"Band {i + 1} upper limit must exceed its lower limit.")
                expect = hi
        if r.tiers[-1][1] is not None:
            raise TaxConfigError("The last band must be open-ended (no upper limit).")


def select_rule(rules: Iterable[Rule], tax_type: str, jurisdiction: str, on: date, category: Optional[str] = None) -> Rule:
    """The most specific rule in force: a category match beats a general rule; two equally specific rules are ambiguous."""
    hits = [r for r in rules if r.tax_type == tax_type and r.jurisdiction == jurisdiction and r.applies_on(on) and (r.category is None or r.category == category)]
    if not hits:
        raise LookupError(f"No tax rule in force for {tax_type} / {jurisdiction}" + (f" / {category}" if category else "") + f" on {on}.")
    specific = [r for r in hits if r.category is not None]
    pool = specific or hits
    if len(pool) > 1:
        raise TaxConfigError("Ambiguous tax configuration: " + ", ".join(sorted(r.code for r in pool)) + " all match.")
    return pool[0]


def calculate(rule: Rule, amount, *, tax_inclusive: Optional[bool] = None) -> Result:
    validate_rule(rule)
    base = D(amount)
    sign = -1 if base < 0 else 1
    mag = abs(base)
    inclusive = rule.inclusive if tax_inclusive is None else bool(tax_inclusive)
    if inclusive and rule.method == "tiered":
        raise TaxConfigError("A tiered rule cannot be tax-inclusive.")
    trace = [f"Rule {rule.code} ({rule.method})", f"Base {base}"]
    if rule.method == "percentage":
        if inclusive:
            tax = quantize(mag - mag / (1 + rule.rate / HUNDRED), rule.precision)
            taxable = mag - tax
            trace.append(f"Inclusive: {mag} gross at {rule.rate}% contains {tax} tax")
        else:
            taxable = mag
            tax = quantize(mag * rule.rate / HUNDRED, rule.precision)
            trace.append(f"{mag} x {rule.rate}%")
        rate = rule.rate
    elif rule.method == "fixed":
        taxable = mag
        tax = quantize(rule.fixed_amount, rule.precision) if mag else ZERO
        rate = ZERO
        trace.append(f"Fixed {tax}" if mag else "Fixed amount not applied to a zero base")
    else:
        taxable, tax = mag, ZERO
        for lo, hi, r in rule.tiers:
            width = max(ZERO, (min(mag, hi) if hi is not None else mag) - lo)
            if width:
                part = width * r / HUNDRED
                tax += part
                trace.append(f"Band {lo}-{hi if hi is not None else 'open'}: {width} x {r}%")
        tax = quantize(tax, rule.precision)
        rate = quantize(tax / mag * HUNDRED, 4) if mag else ZERO
    recoverable = quantize(tax * rule.recoverability_percent / HUNDRED, rule.precision)
    non_rec = tax - recoverable
    trace.append(f"Tax {tax}; recoverable {recoverable} ({rule.recoverability_percent}%)")
    s = Decimal(sign)
    return Result(rule.code, rule.tax_type, rule.jurisdiction, taxable * s, tax * s, recoverable * s, non_rec * s, rate, tuple(trace))


def withhold(result: Result, gross) -> dict:
    """Withholding on a payment: the net payable to the payee is the gross less the tax withheld."""
    g = D(gross)
    return {"gross": g, "withheld": result.tax_amount, "net_payable": g - result.tax_amount}
