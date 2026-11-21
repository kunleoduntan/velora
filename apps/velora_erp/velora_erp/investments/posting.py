"""Ledger postings for investments, and the running position of each holding.

Every posting goes through the VeloraERP posting engine exactly once (idempotent). The position of an investment (units, cost, revaluation, income recognised/received,
tax withheld, realised gain) is never edited by hand: `recompute` rebuilds it from the investment's purchase and its posted transactions.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from velora import get_doc, get_list, throw

from velora_erp.finance.doctype._utils import db_update, db_update_child
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.validation import row

from . import calculations as calc
from .settings import get_settings

NO_APPROVAL = {"Income Accrual", "Bonus Issue"}           # calculated by formula / no ledger effect: nothing for a second person to judge
FIXED_ONLY = {"Income Accrual", "Interest Received", "Upfront Income Received"}
EFFECT_FIELDS = ("d_units", "d_cost", "d_fair_value", "d_accrued", "d_received", "d_wht", "d_realised")
ZERO = Decimal("0.00")
D, money = calc.D, calc.money


def _line(account, debit=0, credit=0, description="", cost_centre=None):
    return {"account": account, "debit": money(debit), "credit": money(credit), "line_description": description, "cost_centre": cost_centre or None}


def _need(value, label):
    if not value:
        throw(f"Set the {label} in Finance Settings > Investments (or on the investment) before posting.")
    return value


def _bank_gl(inv, tx, s):
    bank = (tx.bank_account if tx is not None else None) or inv.bank_account or s.get("bank_account")
    if not bank:
        throw("Choose the bank account for this investment or transaction (or set a default in Finance Settings > Investments).")
    r = row("Bank Account", bank, "name", "gl_account", "disabled")
    if not r or r["disabled"]:
        throw(f"Bank Account {bank!r} does not exist or is disabled.")
    return r["gl_account"]


def _income_account(inv, s, kind):
    if inv.income_account:
        return inv.income_account
    key = {"interest": "interest_income_account", "dividend": "dividend_income_account", "rental": "rental_income_account"}[kind]
    return _need(s.get(key), {"interest": "interest income account", "dividend": "dividend income account", "rental": "rental income account"}[kind])


def _accrued_account(inv, s):
    return inv.accrued_income_account or _need(s.get("accrued_income_account"), "accrued income receivable account")


def _wht_account(s):
    if s.get("wht_treatment") == "Final tax (expense)":
        return _need(s.get("wht_expense_account"), "withholding tax expense account")
    return _need(s.get("wht_receivable_account"), "withholding tax credit receivable account")


def _wht(inv, gross, supplied):
    if supplied not in (None, ""):
        value = money(supplied)
        if value < 0 or value > money(gross):
            throw("Withholding tax cannot be negative or more than the gross amount.")
        return value
    return money(D(gross) * D(inv.wht_rate) / 100) if inv.wht_applicable else ZERO


def pre_accrual(inv, as_of: date) -> Decimal:
    """Income earned up to `as_of` and not yet recognised (fixed income only)."""
    if not calc.is_fixed_income(inv.investment_class):
        return ZERO
    earned = calc.accrued_to(inv.expected_gross_income, inv.start_date, inv.maturity_date, as_of, inv.day_count or "Actual/365")
    return max(ZERO, money(earned - D(inv.income_accrued)))


def _accrual_pair(inv, s, amount, label="Income earned to date"):
    if amount <= 0:
        return []
    source = _accrued_account(inv, s) if inv.payment_mode != "Upfront" else _need(s.get("deferred_income_account"), "deferred income account")
    return [_line(source, debit=amount, description=label, cost_centre=inv.cost_centre), _line(_income_account(inv, s, "interest"), credit=amount, description=label, cost_centre=inv.cost_centre)]


def _blank_effects():
    return {f: ZERO for f in EFFECT_FIELDS} | {"d_units": 0.0, "income_accrued_now": ZERO, "net_cash": ZERO, "carrying_released": ZERO, "gain_loss": ZERO}


def plan(inv, tx, s=None):
    """What this transaction does: (ledger lines, effects). Also fills the defaults the user left empty (amount, tax). Nothing is written here."""
    s = s or get_settings()
    kind, on = tx.transaction_type, tx.transaction_date
    fixed = calc.is_fixed_income(inv.investment_class)
    eff = _blank_effects()
    lines: list[dict] = []
    if inv.docstatus != 1 or inv.status in ("Draft", "Cancelled", "Closed", "Matured"):
        throw(f"Investment {inv.name} is not open ({inv.status}); transactions can only be recorded on an active, submitted investment.")
    if on is None or str(on) < str(inv.start_date):
        throw("The transaction date cannot be before the investment's start date.")
    if kind in FIXED_ONLY and not fixed:
        throw(f"{kind} applies to money-market and fixed-income investments only.")
    cc = inv.cost_centre

    if kind == "Income Accrual":
        amount = pre_accrual(inv, on)
        if amount <= 0:
            throw(f"No new income has been earned up to {on}; it is already recognised.")
        lines = _accrual_pair(inv, s, amount)
        eff.update(d_accrued=amount, income_accrued_now=amount)
        tx.amount = amount
    elif kind == "Upfront Income Received":
        if inv.payment_mode != "Upfront":
            throw("Upfront income applies to an investment whose income is paid upfront.")
        gross = money(tx.amount) if D(tx.amount) > 0 else money(D(inv.expected_gross_income) - D(inv.income_received))
        if gross <= 0 or gross + D(inv.income_received) > D(inv.expected_gross_income) + D("0.01"):
            throw("The upfront income is more than the income expected over the tenor, or nothing is left to receive.")
        wht = _wht(inv, gross, tx.wht_amount)
        net = money(gross - wht)
        lines = [_line(_bank_gl(inv, tx, s), debit=net, description=f"Upfront income: {inv.investment_name}")]
        if wht:
            lines.append(_line(_wht_account(s), debit=wht, description="Tax withheld at source"))
        lines.append(_line(_need(s.get("deferred_income_account"), "deferred income account"), credit=gross, description="Income received in advance", cost_centre=cc))
        eff.update(d_received=gross, d_wht=wht, net_cash=net)
        tx.amount, tx.wht_amount = gross, wht
    elif kind == "Interest Received":
        if inv.payment_mode == "Upfront":
            throw("This investment pays its income upfront; use Upfront Income Received.")
        earned = pre_accrual(inv, on)
        open_after = money(D(inv.income_accrued) + earned - D(inv.income_received))
        if D(tx.amount) > 0:
            gross = money(tx.amount)
        else:
            due = [r for r in (inv.schedule or []) if r.status in ("Scheduled", "Part received", "Overdue")]
            gross = money(D(due[0].gross_interest) - D(due[0].received_amount)) if due else open_after
        if gross <= 0:
            throw("There is no income to receive on this date.")
        if gross > open_after + D("0.01"):
            throw(f"Income received ({gross:,.2f}) is more than the income earned and not yet received up to {on} ({open_after:,.2f}). Check the date or the amount.")
        wht, fee = _wht(inv, gross, tx.wht_amount), money(tx.fee_amount)
        net = money(gross - wht - fee)
        if net < 0:
            throw("Tax and fees are more than the income received.")
        lines = _accrual_pair(inv, s, earned)
        lines.append(_line(_bank_gl(inv, tx, s), debit=net, description=f"Income received: {inv.investment_name}"))
        if wht:
            lines.append(_line(_wht_account(s), debit=wht, description="Tax withheld at source"))
        if fee:
            lines.append(_line(_need(s.get("investment_expense_account"), "investment fees account"), debit=fee, description="Management fee", cost_centre=cc))
        lines.append(_line(_accrued_account(inv, s), credit=gross, description="Settlement of accrued income"))
        eff.update(d_accrued=earned, d_received=gross, d_wht=wht, income_accrued_now=earned, net_cash=net)
        tx.amount, tx.wht_amount, tx.fee_amount = gross, wht, fee
    elif kind in ("Dividend Received", "Rental Received"):
        ok = ("Equity / Shares", "Mutual Fund / Unit Trust", "Private Equity", "Other") if kind == "Dividend Received" else ("Real Estate", "Other")
        if inv.investment_class not in ok:
            throw(f"{kind} does not apply to a {inv.investment_class}.")
        gross = money(tx.amount)
        if gross <= 0:
            throw("Enter the gross amount received.")
        wht = _wht(inv, gross, tx.wht_amount)
        net = money(gross - wht)
        lines = [_line(_bank_gl(inv, tx, s), debit=net, description=f"{kind}: {inv.investment_name}")]
        if wht:
            lines.append(_line(_wht_account(s), debit=wht, description="Tax withheld at source"))
        lines.append(_line(_income_account(inv, s, "dividend" if kind == "Dividend Received" else "rental"), credit=gross, description=kind, cost_centre=cc))
        eff.update(d_accrued=gross, d_received=gross, d_wht=wht, income_accrued_now=gross, net_cash=net)
        tx.amount, tx.wht_amount = gross, wht
    elif kind in ("Property Expense", "Fee Paid"):
        amount = money(tx.amount)
        if amount <= 0:
            throw("Enter the amount paid.")
        lines = [_line(_need(s.get("investment_expense_account"), "investment fees and expenses account"), debit=amount, description=kind, cost_centre=cc),
                 _line(_bank_gl(inv, tx, s), credit=amount, description=f"{kind}: {inv.investment_name}")]
        eff.update(net_cash=-amount)
    elif kind == "Additional Purchase":
        if fixed:
            throw("Record a new placement as a new investment; a top-up applies to shares, funds, property and similar holdings.")
        units = D(tx.units)
        cost = money(tx.amount) if D(tx.amount) > 0 else money(units * D(tx.price_per_unit))
        fee = money(tx.fee_amount)
        if cost <= 0:
            throw("Enter the cost, or the units and price.")
        lines = [_line(inv.investment_account, debit=cost + fee, description=f"Additional purchase: {inv.investment_name}", cost_centre=cc), _line(_bank_gl(inv, tx, s), credit=cost + fee, description="Payment")]
        eff.update(d_units=float(units), d_cost=cost + fee, net_cash=-(cost + fee))
        tx.amount = cost
    elif kind == "Bonus Issue":
        if D(tx.units) <= 0:
            throw("Enter the bonus units received.")
        if inv.investment_class not in ("Equity / Shares", "Mutual Fund / Unit Trust"):
            throw("A bonus issue applies to shares and funds.")
        eff.update(d_units=float(D(tx.units)))
    elif kind == "Revaluation":
        if inv.measurement == "Amortised cost / Cost":
            throw("This investment is carried at cost, so it cannot be revalued. Change the measurement to a fair value basis first.")
        held = D(inv.units_held)
        new_fair = money(held * D(tx.price_per_unit)) if held > 0 and D(tx.price_per_unit) > 0 else money(tx.amount)
        if new_fair <= 0:
            throw("Enter the new price per unit, or the new fair value.")
        diff = money(new_fair - D(inv.carrying_amount))
        if diff == 0:
            throw("The fair value equals the carrying amount; there is nothing to post.")
        target = s.get("fair_value_reserve_account") if inv.measurement == "Fair value through OCI" else s.get("unrealised_gain_loss_account")
        target = _need(target, "fair value reserve account" if inv.measurement == "Fair value through OCI" else "unrealised gain or loss account")
        lines = [_line(inv.investment_account, debit=max(diff, ZERO), credit=max(-diff, ZERO), description="Revaluation", cost_centre=cc),
                 _line(target, debit=max(-diff, ZERO), credit=max(diff, ZERO), description="Revaluation", cost_centre=cc)]
        eff.update(d_fair_value=diff, gain_loss=diff)
        tx.amount = new_fair
    elif kind in ("Part Disposal", "Maturity", "Full Disposal"):
        held, carrying, cost_held = D(inv.units_held), D(inv.carrying_amount), D(inv.cost_basis)
        if kind == "Part Disposal":
            units = D(tx.units)
            if held <= 0 or units <= 0 or units >= held:
                throw("A part disposal needs units, fewer than you hold. Use Full Disposal to sell everything.")
            share = units / held
            released = money(carrying * share)
            cost_part = money(cost_held * share)
            eff["d_units"] = -float(units)
        else:
            released, cost_part = money(carrying), money(cost_held)
            eff["d_units"] = -float(held)
        earned = pre_accrual(inv, on) if fixed else ZERO
        open_accrued = money(D(inv.income_accrued) + earned - D(inv.income_received)) if fixed else ZERO
        open_accrued = max(open_accrued, ZERO)
        if D(tx.amount) > 0:
            proceeds = money(tx.amount)
        elif kind == "Maturity":
            proceeds = money(released + open_accrued)
        elif kind == "Part Disposal" and D(tx.price_per_unit) > 0:
            proceeds = money(D(tx.units) * D(tx.price_per_unit))
        else:
            throw("Enter the sale proceeds (or units and price).")
        wht = _wht(inv, open_accrued, tx.wht_amount) if (fixed and open_accrued > 0) else money(tx.wht_amount)
        fee = money(tx.fee_amount)
        net = money(proceeds - wht - fee)
        if net < 0:
            throw("Tax and fees are more than the proceeds.")
        lines = _accrual_pair(inv, s, earned)
        lines.append(_line(_bank_gl(inv, tx, s), debit=net, description=f"{kind}: {inv.investment_name}"))
        if wht:
            lines.append(_line(_wht_account(s), debit=wht, description="Tax withheld at source"))
        if fee:
            lines.append(_line(_need(s.get("investment_expense_account"), "investment fees account"), debit=fee, description="Charges", cost_centre=cc))
        lines.append(_line(inv.investment_account, credit=released, description="Carrying amount released", cost_centre=cc))
        if open_accrued > 0:
            lines.append(_line(_accrued_account(inv, s), credit=open_accrued, description="Settlement of accrued income"))
        realised = money(proceeds - released - open_accrued)
        if realised != 0:
            lines.append(_line(_need(s.get("realised_gain_loss_account"), "realised gain or loss account"), debit=max(-realised, ZERO), credit=max(realised, ZERO), description="Gain / (loss) on disposal", cost_centre=cc))
        eff.update(d_cost=-cost_part, d_fair_value=-(released - cost_part), d_accrued=earned, d_received=open_accrued, d_wht=wht, d_realised=realised, income_accrued_now=earned,
                   net_cash=net, carrying_released=released, gain_loss=realised)
        tx.amount, tx.wht_amount, tx.fee_amount = proceeds, wht, fee
    else:
        throw(f"Unknown transaction type {kind!r}.")
    tx.income_accrued_now, tx.net_cash, tx.carrying_released, tx.gain_loss = eff["income_accrued_now"], eff["net_cash"], eff["carrying_released"], eff["gain_loss"]
    return [l for l in lines if l["debit"] or l["credit"]], eff


def post_transaction(tx):
    inv = get_doc("Investment", tx.investment, ignore_permissions=True)
    lines, eff = plan(inv, tx)
    batch = None
    if lines:
        batch = post_financial_transaction(source_doctype="Investment Transaction", source_name=tx.name, posting_date=tx.transaction_date, currency=inv.currency, exchange_rate=inv.exchange_rate or 1, lines=lines,
                                           posting_event="Original", remarks=f"{tx.transaction_type}: {inv.investment_name}", idempotency_key=f"investment-transaction:{tx.name}")
    values = {k: eff[k] for k in EFFECT_FIELDS}
    values.update(income_accrued_now=eff["income_accrued_now"], net_cash=eff["net_cash"], carrying_released=eff["carrying_released"], gain_loss=eff["gain_loss"], amount=tx.amount,
                  wht_amount=tx.wht_amount, fee_amount=tx.fee_amount, status="Posted", posting_batch=batch.name if batch else None)
    db_update(tx, **values)
    if tx.transaction_type == "Revaluation" and D(tx.price_per_unit) > 0:
        db_update(inv, market_price=tx.price_per_unit)
    recompute(inv.name)
    return batch


def post_purchase(inv):
    s = get_settings()
    cost = money(D(inv.principal) + D(inv.acquisition_costs))
    if cost <= 0:
        throw("The amount invested must be greater than zero.")
    lines = [_line(inv.investment_account, debit=cost, description=f"Purchase: {inv.investment_name}", cost_centre=inv.cost_centre), _line(_bank_gl(inv, None, s), credit=cost, description=f"Payment: {inv.investment_name}")]
    batch = post_financial_transaction(source_doctype="Investment", source_name=inv.name, posting_date=inv.start_date, currency=inv.currency, exchange_rate=inv.exchange_rate or 1, lines=lines,
                                       posting_event="Original", remarks=f"Purchase of {inv.investment_name}", idempotency_key=f"investment:{inv.name}:purchase")
    db_update(inv, posting_batch=batch.name)
    recompute(inv.name)
    return batch


def recompute(name: str) -> dict:
    """Rebuild the position of one investment from its purchase and its posted transactions."""
    inv = get_doc("Investment", name, ignore_permissions=True)
    txs = get_list("Investment Transaction", filters={"investment": name, "docstatus": 1, "status": "Posted"}, fields=["name", "transaction_type", "transaction_date", *EFFECT_FIELDS],
                   order_by="transaction_date asc", limit=100000, ignore_permissions=True)
    cost0 = money(D(inv.principal) + D(inv.acquisition_costs))
    total = {f: D(0) for f in EFFECT_FIELDS}
    for t in txs:
        for f in EFFECT_FIELDS:
            total[f] += D(t[f])
    units_held = float(D(inv.units) + total["d_units"])
    cost_basis = money(cost0 + total["d_cost"])
    fair_adj = money(total["d_fair_value"])
    kinds = [t["transaction_type"] for t in txs]
    if "Maturity" in kinds:
        status = "Matured"
    elif "Full Disposal" in kinds:
        status = "Closed"
    elif "Part Disposal" in kinds:
        status = "Part Disposed"
    else:
        status = "Active"
    last = [t["transaction_date"] for t in txs if t["transaction_type"] in ("Income Accrual", "Interest Received", "Maturity", "Full Disposal") and D(t["d_accrued"]) != 0]
    rows = calc.apply_receipts([{"gross_interest": r.gross_interest, "due_date": r.due_date, "status": r.status, "received_amount": r.received_amount, "_name": r.name} for r in inv.schedule or []],
                               total["d_received"] if calc.is_fixed_income(inv.investment_class) else 0)
    nxt = next((r["due_date"] for r in rows if r["status"] in ("Scheduled", "Part received", "Overdue")), None)
    values = dict(units_held=units_held, cost_basis=cost_basis, fair_value_adjustment=fair_adj, carrying_amount=money(cost_basis + fair_adj), income_accrued=money(total["d_accrued"]),
                  income_received=money(total["d_received"]), accrued_receivable=money(total["d_accrued"] - total["d_received"]), wht_suffered=money(total["d_wht"]),
                  realised_gain_loss=money(total["d_realised"]), last_accrual_date=max(last) if last else None, next_payment_date=nxt if status in ("Active", "Part Disposed") else None, status=status)
    db_update(inv, **values)
    for r in rows:
        db_update_child("Investment Schedule Line", r["_name"], status=r["status"], received_amount=r["received_amount"])
    return values
