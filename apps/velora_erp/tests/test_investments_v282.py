from datetime import date, timedelta
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_cash_transactions import setup_cash, approve, MAKER, APPROVER
from velora_erp.finance.engine import get_account_balance
from velora_erp.investments import calculations as calc, jobs, posting
from velora_erp.investments.api import rollover
from velora_erp.investments.portfolio import portfolio

T = date.today()
Y = T.year
JAN1 = date(Y, 1, 1)


def D(v):
    return Decimal(str(v))


def setup_inv(tmp_path, **settings):
    accounts, customer, supplier = setup_cash(tmp_path)
    extra = {}
    for code, name, group, kind in [
        ("1500", "Investments", "A", "INVESTMENT"), ("1510", "Accrued Income", "A", "ACCRUED_INCOME"), ("1520", "WHT Credit", "A", "TAX_RECEIVABLE"),
        ("2300", "Deferred Income", "L", "DEFERRED_INCOME"), ("3100", "Fair Value Reserve", "E", "EQUITY"), ("4100", "Interest Income", "I", "REVENUE"),
        ("4110", "Dividend Income", "I", "REVENUE"), ("4120", "Rental Income", "I", "REVENUE"), ("4200", "Realised Gain", "I", "OTHER_INCOME"), ("4210", "Unrealised Gain", "I", "OTHER_INCOME"),
        ("5100", "Investment Costs", "X", "OPERATING_EXPENSE"), ("5200", "WHT Expense", "X", "OPERATING_EXPENSE"),
    ]:
        extra[code] = new_doc("Account", account_code=code, account_name=name, account_group=group, account_type=kind, allow_manual_posting=1).insert(ignore_permissions=True)
    bank = new_doc("Bank Account", account_code="MAIN", account_name="Main", gl_account=accounts["1000"].name).insert(ignore_permissions=True)
    values = dict(bank_account=bank.name, interest_income_account=extra["4100"].name, dividend_income_account=extra["4110"].name,
                  rental_income_account=extra["4120"].name, accrued_income_account=extra["1510"].name, deferred_income_account=extra["2300"].name, wht_receivable_account=extra["1520"].name,
                  wht_expense_account=extra["5200"].name, realised_gain_loss_account=extra["4200"].name, unrealised_gain_loss_account=extra["4210"].name,
                  fair_value_reserve_account=extra["3100"].name, investment_expense_account=extra["5100"].name)
    values.update(settings)
    from velora import get_doc, get_list
    from velora_erp.investments.settings import field_for
    fs = get_doc("Finance Settings", get_list("Finance Settings", fields=["name"], limit=1, ignore_permissions=True)[0]["name"], ignore_permissions=True)
    for key, value in values.items():
        fs.set(field_for(key), value)
    fs.save(ignore_permissions=True)
    return {**accounts, **extra}, bank


def bal(accounts, code):
    return get_account_balance(accounts[code].name)


def make_investment(accounts, **kw):
    base = dict(investment_name="Test", investment_class="Fixed Deposit", counterparty="Bank A", currency="NGN", investment_account=accounts["1500"].name, start_date=JAN1)
    base.update(kw)
    with session_as(MAKER):
        inv = new_doc("Investment", **base).insert()
    return approve(inv)


def make_tx(inv, kind, on, **kw):
    with session_as(MAKER):
        tx = new_doc("Investment Transaction", investment=inv.name, transaction_type=kind, transaction_date=on, **kw).insert()
    return tx


def post(tx):
    if tx.transaction_type in posting.NO_APPROVAL:
        tx.submit(ignore_permissions=True)
        tx.reload()
        return tx
    return approve(tx)


def fd(accounts, **kw):
    return make_investment(accounts, **{**dict(principal=1000000, interest_rate=12, tenor_days=181), **kw})


def test_pure_arithmetic_ties_out():
    assert calc.total_gross_income("Simple Interest", 1000000, 0, 12, 181) == D("59506.85")
    price = calc.discount_price(1000000, 18, 182)
    assert price == D("910246.58")
    rows = calc.build_schedule(JAN1, JAN1 + timedelta(days=365), D("100000.01"), "Periodic", "Quarterly", 10, 0)
    assert len(rows) == 4 and sum(r["gross_interest"] for r in rows) == D("100000.01")
    assert calc.accrued_to(1000, JAN1, JAN1 + timedelta(days=100), JAN1 + timedelta(days=50)) == D("500.00")
    assert calc.accrued_to(1000, JAN1, JAN1 + timedelta(days=100), JAN1 + timedelta(days=500)) == D("1000.00")


def test_fixed_deposit_full_cycle_posts_correctly(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        inv = fd(accounts)
        assert inv.status == "Active" and inv.posting_batch and inv.expected_gross_income == D("59506.85") and inv.maturity_date == JAN1 + timedelta(days=181)
        assert bal(accounts, "1500") == D(1000000) and bal(accounts, "1000") == D(-1000000)
        accrual = post(make_tx(inv, "Income Accrual", date(Y, 3, 31)))
        inv.reload()
        expected = calc.accrued_to(inv.expected_gross_income, JAN1, inv.maturity_date, date(Y, 3, 31))
        assert accrual.amount == expected and inv.income_accrued == expected and inv.accrued_receivable == expected
        assert bal(accounts, "1510") == expected and bal(accounts, "4100") == -expected
        with pytest.raises(ValidationError):
            post(make_tx(inv, "Income Accrual", date(Y, 3, 31)))                    # nothing new to accrue
        mat = post(make_tx(inv, "Maturity", inv.maturity_date))
        inv.reload()
        assert inv.status == "Matured" and inv.carrying_amount == 0 and inv.accrued_receivable == 0 and inv.income_accrued == D("59506.85")
        assert mat.wht_amount == D("5950.69") and mat.amount == D("1059506.85") and mat.gain_loss == 0
        assert bal(accounts, "1500") == 0 and bal(accounts, "1510") == 0
        assert bal(accounts, "1000") == D("-1000000") + D("1059506.85") - D("5950.69")
        assert bal(accounts, "1520") == D("5950.69") and bal(accounts, "4100") == -D("59506.85")
        assert inv.wht_suffered == D("5950.69")
    finally:
        velora.shutdown()


def test_periodic_income_marks_schedule_and_cannot_exceed_earnings(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        inv = make_investment(accounts, investment_class="Bond", investment_name="FGN Bond", principal=500000, face_value=500000, interest_rate=10, tenor_days=365,
                              payment_mode="Periodic", payment_frequency="Half-yearly", interest_method="Coupon (Bond)")
        assert len(inv.schedule) == 2 and sum(r.gross_interest for r in inv.schedule) == inv.expected_gross_income
        with pytest.raises(ValidationError):                                         # nothing earned yet on day one
            post(make_tx(inv, "Interest Received", JAN1 + timedelta(days=1), amount=inv.schedule[0].gross_interest))
        first = inv.schedule[0]
        rec = post(make_tx(inv, "Interest Received", first.period_end))
        inv.reload()
        assert rec.amount == first.gross_interest and inv.income_received == first.gross_interest
        assert [r.status for r in inv.schedule][0] == "Received" and inv.next_payment_date == inv.schedule[1].due_date
        assert bal(accounts, "1510") == 0 and rec.income_accrued_now == first.gross_interest       # earned and received in one go: receivable settles
    finally:
        velora.shutdown()


def test_treasury_bill_cost_from_discount_and_maturity_at_face(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        inv = make_investment(accounts, investment_class="Treasury Bill", investment_name="364-day bill", face_value=1000000, interest_rate=18, tenor_days=182)
        assert inv.principal == D("910246.58") and inv.expected_gross_income == D("89753.42") and inv.wht_applicable == 0
        mat = post(make_tx(inv, "Maturity", inv.maturity_date))
        inv.reload()
        assert mat.amount == D("1000000.00") and mat.wht_amount == 0 and inv.status == "Matured" and inv.income_accrued == D("89753.42")
        assert bal(accounts, "1500") == 0 and bal(accounts, "1000") == D("89753.42") and bal(accounts, "4100") == -D("89753.42")
        with pytest.raises(ValidationError):
            make_investment(accounts, investment_class="Treasury Bill", face_value=100, principal=100, interest_rate=0, tenor_days=90)   # cost must be below face
    finally:
        velora.shutdown()


def test_equity_dividend_revaluation_and_part_disposal(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        inv = make_investment(accounts, investment_class="Equity / Shares", investment_name="Bank shares", units=1000, unit_cost=50)
        assert inv.principal == 50000 and inv.units_held == 1000 and inv.measurement == "Fair value through profit or loss"
        reval = post(make_tx(inv, "Revaluation", date(Y, 6, 30), price_per_unit=60))
        inv.reload()
        assert reval.gain_loss == 10000 and inv.carrying_amount == 60000 and bal(accounts, "4210") == -10000
        div = post(make_tx(inv, "Dividend Received", date(Y, 7, 1), amount=2000))
        assert div.wht_amount == 200 and div.net_cash == 1800 and bal(accounts, "4110") == -2000 and bal(accounts, "1520") == 200
        sale = post(make_tx(inv, "Part Disposal", date(Y, 8, 1), units=400, price_per_unit=65))
        inv.reload()
        assert sale.carrying_released == 24000 and sale.gain_loss == 2000 and bal(accounts, "4200") == -2000
        assert inv.units_held == 600 and inv.carrying_amount == 36000 and inv.cost_basis == 30000 and inv.status == "Part Disposed"
        top = post(make_tx(inv, "Additional Purchase", date(Y, 9, 1), units=100, price_per_unit=70))
        inv.reload()
        assert inv.units_held == 700 and inv.cost_basis == 37000
        with pytest.raises(ValidationError):
            post(make_tx(inv, "Part Disposal", date(Y, 9, 2), units=700, price_per_unit=1))   # cannot sell everything as a part disposal
    finally:
        velora.shutdown()


def test_cost_measurement_blocks_revaluation_and_fair_value_oci_uses_reserve(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        dep = fd(accounts)
        with pytest.raises(ValidationError):
            make_tx(dep, "Revaluation", date(Y, 6, 1), amount=1)
        prop = make_investment(accounts, investment_class="Real Estate", investment_name="Plot", principal=20000000, acquisition_costs=500000, measurement="Fair value through OCI",
                               expected_annual_rent=1200000)
        assert prop.asset_group == "Real Estate" and prop.carrying_amount == 20500000 and prop.effective_yield == 6.0
        post(make_tx(prop, "Revaluation", date(Y, 6, 30), amount=23000000))
        prop.reload()
        assert prop.carrying_amount == 23000000 and bal(accounts, "3100") == -2500000 and bal(accounts, "4210") == 0
        rent = post(make_tx(prop, "Rental Received", date(Y, 7, 1), amount=300000, wht_amount=0))
        post(make_tx(prop, "Property Expense", date(Y, 7, 2), amount=40000))
        assert bal(accounts, "4120") == -300000 and bal(accounts, "5100") == 40000
    finally:
        velora.shutdown()


def test_upfront_income_is_deferred_then_released(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        inv = fd(accounts, payment_mode="Upfront")
        recv = post(make_tx(inv, "Upfront Income Received", JAN1))
        assert recv.amount == D("59506.85") and bal(accounts, "2300") == -D("59506.85") and bal(accounts, "1000") == D(-1000000) + D("53556.16")
        post(make_tx(inv, "Income Accrual", date(Y, 3, 31)))
        inv.reload()
        assert bal(accounts, "2300") == -D("59506.85") + inv.income_accrued and inv.accrued_receivable == inv.income_accrued - D("59506.85")
    finally:
        velora.shutdown()


def test_cancel_is_newest_first_and_restores_the_position(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        inv = fd(accounts)
        acc = post(make_tx(inv, "Income Accrual", date(Y, 2, 28)))
        mat = post(make_tx(inv, "Maturity", inv.maturity_date))

        def cancel(doc):
            with session_as(APPROVER):
                d = get_doc(doc.doctype, doc.name)
                d.cancel(reason="wrong")
            return d
        with pytest.raises(ValidationError):
            cancel(acc)                                                              # a later transaction still stands
        cancel(mat)
        inv.reload()
        assert inv.status == "Active" and inv.carrying_amount == 1000000
        cancel(acc)
        inv.reload()
        assert inv.income_accrued == 0 and bal(accounts, "1510") == 0 and bal(accounts, "4100") == 0
        with pytest.raises(ValidationError):
            cancel(acc)                                                              # already cancelled
        cancel(inv)
        inv.reload()
        assert inv.status == "Cancelled" and bal(accounts, "1500") == 0
    finally:
        velora.shutdown()


def test_investment_approval_follows_the_companys_workflow(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        from wf_helpers import install_approval, decide
        from velora_erp.finance.workflow_templates import approval_doctypes
        assert "Investment" in approval_doctypes()
        with session_as(MAKER):                                                      # no workflow: no approval step
            plain = new_doc("Investment", investment_name="Plain", investment_class="Fixed Deposit", counterparty="Bank", currency="NGN", investment_account=accounts["1500"].name,
                            start_date=JAN1, principal=1000, interest_rate=10, tenor_days=30).insert()
        plain.submit(ignore_permissions=True)
        install_approval("Investment")
        with session_as(MAKER):
            inv = new_doc("Investment", investment_name="Unapproved", investment_class="Fixed Deposit", counterparty="Bank", currency="NGN", investment_account=accounts["1500"].name,
                          start_date=JAN1, principal=1000, interest_rate=10, tenor_days=30).insert()
        with pytest.raises(ValidationError, match="approval workflow"):
            inv.submit(ignore_permissions=True)
        decide("Investment", inv.name, "Approve", APPROVER)
        get_doc("Investment", inv.name).submit(ignore_permissions=True)
        assert get_doc("Investment", inv.name).status == "Active"
    finally:
        velora.shutdown()


def test_accrue_all_is_idempotent_and_portfolio_flags_concentration(tmp_path):
    accounts, _ = setup_inv(tmp_path, max_counterparty_percent=40)
    try:
        a = fd(accounts, investment_name="Big", counterparty="Bank A", principal=3000000)
        b = fd(accounts, investment_name="Small", counterparty="Bank B", principal=1000000)
        eq = make_investment(accounts, investment_class="Equity / Shares", investment_name="Shares", counterparty="Broker", units=100, unit_cost=100, start_date=JAN1)
        first = jobs.accrue_all(date(Y, 3, 31))
        assert len(first["posted"]) == 2 and not first["failed"]
        assert jobs.accrue_all(date(Y, 3, 31))["posted"] == []                      # nothing new the second time
        pf = portfolio(date(Y, 3, 31))
        assert pf["kpis"]["holdings"] == 3 and pf["kpis"]["carrying"] == 4010000
        assert [g["label"] for g in pf["by_group"]] == ["Money Market", "Capital Market"]
        assert any("Bank A" in x["message"] for x in pf["alerts"] if x["kind"] == "concentration")
        assert pf["kpis"]["accrued_receivable"] > 0 and sum(x["count"] for x in pf["ladder"]) == 2
        assert pf["by_counterparty"][0]["label"] == "Bank A" and pf["by_counterparty"][0]["over_limit"]
    finally:
        velora.shutdown()


def test_rollover_drafts_the_next_placement(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        inv = fd(accounts)
        with pytest.raises(ValidationError):
            rollover(inv.name)                                                       # not matured yet
        post(make_tx(inv, "Maturity", inv.maturity_date))
        new = get_doc("Investment", rollover(inv.name, capitalise=True, rate=13)["name"])
        assert new.docstatus == 0 and new.start_date == inv.maturity_date and new.interest_rate == 13
        assert new.principal == D(1000000) + (D("59506.85") - D("5950.69"))
    finally:
        velora.shutdown()


def test_bad_terms_are_rejected(tmp_path):
    accounts, _ = setup_inv(tmp_path)
    try:
        with session_as(MAKER):
            with pytest.raises(ValidationError):
                new_doc("Investment", investment_name="x", investment_class="Fixed Deposit", counterparty="B", currency="NGN", investment_account=accounts["1500"].name, start_date=JAN1,
                        principal=1000, interest_rate=10).insert()                       # no tenor or maturity
            with pytest.raises(ValidationError):
                new_doc("Investment", investment_name="x", investment_class="Equity / Shares", counterparty="B", currency="NGN", investment_account=accounts["1500"].name, start_date=JAN1).insert()
    finally:
        velora.shutdown()
