"""Exchange-rate lookup and base-currency columns for sales and purchase documents."""
from decimal import Decimal, ROUND_HALF_UP
from velora import get_list

CENT = Decimal("0.01")


def _d(v):
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except Exception:
        return Decimal("0")


def base_currency():
    rows = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
    return (rows[0]["base_currency"] if rows and rows[0].get("base_currency") else "").upper()


def lookup_rate_dated(from_currency, to_currency, on_date):
    """Like lookup_rate, also returning the date of the rate used: (rate, effective_date) or (None, None)."""
    from_currency, to_currency = str(from_currency).upper(), str(to_currency).upper()
    if from_currency == to_currency:
        return Decimal("1"), on_date
    on = str(on_date)[:10] if on_date else "9999-12-31"
    for a, b, invert in ((from_currency, to_currency, False), (to_currency, from_currency, True)):
        rows = get_list("Currency Exchange Rate", filters={"from_currency": a, "to_currency": b}, fields=["effective_date", "rate"], order_by="effective_date desc", limit=500, ignore_permissions=True)
        for r in rows:
            if str(r["effective_date"])[:10] <= on:
                rate = _d(r["rate"])
                return ((Decimal("1") / rate) if invert else rate), r["effective_date"]
    return None, None


def lookup_rate(from_currency, to_currency, on_date):
    """Latest dated rate on or before on_date; the inverse of a stored opposite pair is used when only that exists."""
    from_currency, to_currency = str(from_currency).upper(), str(to_currency).upper()
    if from_currency == to_currency:
        return Decimal("1")
    on = str(on_date)[:10] if on_date else "9999-12-31"
    for a, b, invert in ((from_currency, to_currency, False), (to_currency, from_currency, True)):
        rows = get_list("Currency Exchange Rate", filters={"from_currency": a, "to_currency": b}, fields=["effective_date", "rate"], order_by="effective_date desc", limit=500, ignore_permissions=True)
        for r in rows:
            if str(r["effective_date"])[:10] <= on:
                rate = _d(r["rate"])
                return (Decimal("1") / rate) if invert else rate
    return None


def resolve_exchange_rate(doc, date_field):
    """Fill the rate of a foreign-currency document from the master when it was left at 0 or 1."""
    currency = str(getattr(doc, "currency", "") or "").upper()
    if not currency or currency == base_currency():
        return
    entered = _d(getattr(doc, "exchange_rate", 0))
    if entered in (Decimal("0"), Decimal("1")):
        on = getattr(doc, date_field, None)
        found, dated = lookup_rate_dated(currency, base_currency(), on)
        if found:
            doc.exchange_rate = found
            from datetime import date as _date
            try:
                age = (_date.fromisoformat(str(on)[:10]) - _date.fromisoformat(str(dated)[:10])).days if on and dated else 0
            except ValueError:
                age = 0
            if age > 7:
                from velora import warn
                warn(f"The {currency} rate used ({found}) is from {str(dated)[:10]}, {age} days before this document.",
                     hint="If the rate has moved, add today's rate and save again; otherwise nothing to do.",
                     actions=[{"label": "Add exchange rate", "href": "#/app/Currency%20Exchange%20Rate/new"}])
        elif entered == 0:
            from velora import throw
            throw(f"There is no {currency} to {base_currency()} exchange rate on or before {str(on)[:10] if on else 'this date'}.",
                  advice={"hint": f"Type the rate on the document, or add the {currency} rate in Currency Exchange Rate and save again.",
                          "actions": [{"label": "Add exchange rate", "href": "#/app/Currency%20Exchange%20Rate/new"}], "field": "exchange_rate"})
        else:
            from velora import warn
            warn(f"No {currency} to {base_currency()} rate was found, so the rate of 1 on the document is kept.",
                 hint="If that is not the real rate, type it on the document or add it in Currency Exchange Rate.",
                 actions=[{"label": "Add exchange rate", "href": "#/app/Currency%20Exchange%20Rate/new"}])


def apply_base_amounts(doc, *, net_field=None, tax_field=None, total_field=None, base_prefix="base_"):
    """Per-line base rate/amount and base header totals (transaction amount x exchange rate)."""
    fx = _d(getattr(doc, "exchange_rate", 1)) or Decimal("1")
    for line in getattr(doc, "lines", None) or []:
        amount = _d(getattr(line, "amount", 0)); qty = _d(getattr(line, "quantity", 0))
        rate = _d(getattr(line, "rate", 0)) or (amount / qty if qty else Decimal("0"))
        if hasattr(line, "base_amount"):
            line.base_amount = (amount * fx).quantize(CENT, rounding=ROUND_HALF_UP)
        if hasattr(line, "base_rate"):
            line.base_rate = (rate * fx).quantize(CENT, rounding=ROUND_HALF_UP)
    for src, dst in ((net_field, "base_net_amount"), (tax_field, "base_tax_amount"), (total_field, "base_grand_total")):
        if src and hasattr(doc, dst):
            setattr(doc, dst, (_d(getattr(doc, src, 0)) * fx).quantize(CENT, rounding=ROUND_HALF_UP))
