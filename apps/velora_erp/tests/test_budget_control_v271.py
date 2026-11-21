import calendar
from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_cash_transactions import setup_cash, approve, MAKER, APPROVER
from velora_erp.finance import budget_control as bc

T = date.today()
M1 = T.replace(day=1)
M2 = T.replace(day=calendar.monthrange(T.year, T.month)[1])


def _budget(accounts, amount=1000, extra=()):
    with session_as(MAKER):
        b = new_doc("Financial Budget", budget_name="OPEX", budget_scenario="Original", financial_year=f"FY-{T.year}",
                    lines=[{"account": accounts["5000"].name, "period_start": M1, "period_end": M2, "budget_amount": amount}, *extra]).insert()
    with session_as(APPROVER):
        b = get_doc("Financial Budget", b.name); b.approval_status = "Approved"; b.save(); b.submit(); b.reload()
    return b


def _expense(accounts, amount, who=MAKER, note="Office spend"):
    with session_as(MAKER):
        p = new_doc("Payment", payment_date=T, posting_date=T, purpose="Expense Payment", beneficiary="Landlord", currency="NGN",
                    exchange_rate=1, cash_account=accounts["1000"].name, narration=note,
                    lines=[{"account": accounts["5000"].name, "amount": amount}]).insert()
    return approve(p)


def _adjustment(budget, kind, lines, reason="Reforecast"):
    with session_as(MAKER):
        a = new_doc("Budget Adjustment", financial_budget=budget.name, adjustment_type=kind, adjustment_date=T, reason=reason, lines=lines).insert()
    with session_as(APPROVER):
        a = get_doc("Budget Adjustment", a.name); a.approval_status = "Approved"; a.save(); a.submit(); a.reload()
    return a


def test_spread_adds_up_exactly_and_supports_seasonality():
    rows = bc.spread_annual_budget(date(2027, 1, 1), "100000.00")
    assert len(rows) == 12 and sum(r["budget_amount"] for r in rows) == Decimal("100000.00")
    assert rows[0]["period_end"] == date(2027, 1, 31) and rows[1]["period_end"] == date(2027, 2, 28)
    odd = bc.spread_annual_budget(date(2027, 1, 1), "100.00", weights=[1] * 11 + [2])
    assert sum(r["budget_amount"] for r in odd) == Decimal("100.00") and odd[11]["budget_amount"] > odd[0]["budget_amount"]
    with pytest.raises(ValidationError):
        bc.spread_annual_budget(date(2027, 1, 15), 100)


def test_control_off_by_default_then_warn_then_block_with_explicit_override(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        _budget(accounts, 1000)
        _expense(accounts, 1500)                                  # mode Off: no control at all
        bc.set_config(mode="Warn")
        _expense(accounts, 100, note="Over budget but only warns")
        bc.set_config(mode="Block")
        with pytest.raises(ValidationError, match="Budget exceeded"):
            _expense(accounts, 50, note="Blocked")                # the approver's role alone does not bypass it
        with pytest.raises(ValidationError, match="reason is required"):
            with bc.override("  "):
                pass
        with bc.override("MD approved overspend for emergency repairs"):
            _expense(accounts, 50, note="Overridden")
    finally:
        velora.shutdown()


def test_tolerance_period_and_unbudgeted_rules(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        _budget(accounts, 1000)
        bc.set_config(mode="Block", tolerance_percent=10)
        _expense(accounts, 1100)                                  # exactly budget + 10%
        with pytest.raises(ValidationError, match="Budget exceeded"):
            _expense(accounts, 1)
        other = new_doc("Account", account_code="5200", account_name="Travel", account_group="X", account_type="OPERATING_EXPENSE", allow_manual_posting=1).insert(ignore_permissions=True)
        with session_as(MAKER):
            p = new_doc("Payment", payment_date=T, posting_date=T, purpose="Expense Payment", beneficiary="Airline", currency="NGN", exchange_rate=1,
                        cash_account=accounts["1000"].name, narration="Travel", lines=[{"account": other.name, "amount": 500}]).insert()
        approve(p)                                                 # unbudgeted: Allow (default)
        bc.set_config(mode="Block", unbudgeted="Block")
        with session_as(MAKER):
            p2 = new_doc("Payment", payment_date=T, posting_date=T, purpose="Expense Payment", beneficiary="Airline", currency="NGN", exchange_rate=1,
                         cash_account=accounts["1000"].name, narration="Travel 2", lines=[{"account": other.name, "amount": 5}]).insert()
        with pytest.raises(ValidationError, match="unbudgeted"):
            approve(p2)
    finally:
        velora.shutdown()


def test_adjustment_increase_unlocks_spend_and_transfer_rules(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        b = _budget(accounts, 1000)
        bc.set_config(mode="Block")
        with pytest.raises(ValidationError, match="Budget exceeded"):
            _expense(accounts, 1200)
        a = _adjustment(b, "Increase", [{"account": accounts["5000"].name, "period_start": M1, "period_end": M2, "change_amount": 500}])
        assert a.docstatus == 1 and Decimal(str(a.net_change)) == Decimal("500")
        _expense(accounts, 1200)                                   # budget is now 1500
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="net to zero"):
                new_doc("Budget Adjustment", financial_budget=b.name, adjustment_type="Transfer", adjustment_date=T, reason="x",
                        lines=[{"account": accounts["5000"].name, "period_start": M1, "period_end": M2, "change_amount": -100}]).insert()
            with pytest.raises(ValidationError, match="Decrease cannot contain positive"):
                new_doc("Budget Adjustment", financial_budget=b.name, adjustment_type="Decrease", adjustment_date=T, reason="x",
                        lines=[{"account": accounts["5000"].name, "period_start": M1, "period_end": M2, "change_amount": 100}]).insert()
            bad = new_doc("Budget Adjustment", financial_budget=b.name, adjustment_type="Decrease", adjustment_date=T, reason="too deep",
                          lines=[{"account": accounts["5000"].name, "period_start": M1, "period_end": M2, "change_amount": -5000}]).insert()
        with session_as(APPROVER):
            bad = get_doc("Budget Adjustment", bad.name); bad.approval_status = "Approved"; bad.save()
            with pytest.raises(ValidationError, match="below zero"):
                bad.submit()
        # utilisation report reflects original + adjustment and actual spend
        rows = bc.budget_utilisation("OPEX", as_of=T)
        r = rows[0]
        assert (r["original"], r["adjustments"], r["revised"], r["actual"]) == (Decimal("1000"), Decimal("500"), Decimal("1500"), Decimal("1200"))
        assert r["available"] == Decimal("300") and r["utilisation_percent"] == Decimal("80.00")
        # budget-vs-actual provider sees the adjustment too
        from velora_erp.finance.reporting_provider import get_budget_totals
        totals = get_budget_totals([accounts["5000"].name], M1, M2, budget_name="OPEX")
        assert Decimal(str(totals[0]["budget_amount"])) == Decimal("1500")
    finally:
        velora.shutdown()


def test_override_authority_is_configurable_and_service_accounts_cannot_override(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        from velora.permissions import Session
        from velora_erp.finance import approval_authority as aa
        _budget(accounts, 100)
        bc.set_config(mode="Block")
        lines = [{"account": accounts["5000"].name, "debit": 500, "credit": 0}]
        kw = dict(lines=lines, posting_date=T, exchange_rate=1, posting_event="Original", source_doctype="Payment")
        admin = Session("sysadmin@example.test", frozenset({"System Manager"}))
        with session_as(APPROVER):
            with bc.override("approved"):
                assert bc.check_posting(**kw)                      # default: Finance Manager holds budget.override
        with session_as(admin):
            aa.set_authority("budget.override", ["Budget Committee"])
        with session_as(APPROVER):
            with bc.override("approved"):
                with pytest.raises(ValidationError, match="may override"):
                    bc.check_posting(**kw)
        with session_as(admin):
            aa.reset_authority("budget.override")
        with session_as(Session("job@example.test", frozenset({"Finance Manager"}), {"service_account": True})):
            with bc.override("auto"):
                with pytest.raises(ValidationError, match="may override"):
                    bc.check_posting(**kw)
    finally:
        velora.shutdown()
