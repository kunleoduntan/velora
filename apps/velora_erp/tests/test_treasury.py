"""Treasury end to end: facility, drawdown, interest accrual, repayment with tax withheld, cancellation, covenants, insight."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as

from test_invoices_v08 import APPROVER, MAKER, approve_submit, setup
from test_tax_management import _rule
from velora_erp.finance.engine import get_account_balance

D = Decimal


def _world(tmp_path, **fac):
    a = setup(tmp_path)
    def acc(code, name, g, typ):
        return new_doc("Account", account_code=code, account_name=name, account_group={"A": "A", "L": "L", "X": "X"}[g], account_type=typ, allow_manual_posting=1).insert(ignore_permissions=True)
    a["bank"], a["bank2"] = acc("1010", "Main bank", "A", "BANK"), acc("1011", "Second bank", "A", "BANK")
    a["loan"], a["accr"] = acc("2500", "Bank loans", "L", "BORROWING"), acc("2510", "Accrued interest", "L", "ACCRUAL")
    a["int"] = acc("5900", "Interest expense", "X", "FINANCE_COST")
    a["whtpay"] = acc("2220", "WHT payable", "L", "TAX_PAYABLE")
    _rule(a, "WHTINT", 10, a["whtpay"].name, tax_type="WHT")
    a["lender"] = new_doc("Financial Institution", institution_name="First Bank", institution_type="Commercial Bank", wht_applicable=1).insert(ignore_permissions=True)
    y = date.today()
    base = dict(facility_name="Term loan A", financial_institution="First Bank", facility_type="Term Loan", currency="NGN", approved_limit=10_000_000, start_date=y - timedelta(days=400), expiry_date=y + timedelta(days=300),
                interest_rate=20, interest_rate_type="Fixed", repayment_structure="Annuity", repayment_frequency="Monthly", default_tenor_months=12, arrangement_fee_percent=1,
                loan_liability_account=a["loan"].name, interest_expense_account=a["int"].name, accrued_interest_account=a["accr"].name, wht_rule="WHTINT",
                covenants=[{"covenant_name": "Debt service cover", "metric": "Debt Service Cover", "operator": ">=", "threshold": 1.2, "warning_margin": 0.1, "test_frequency": "Quarterly"}])
    base.update(fac)
    with session_as(MAKER):
        f = new_doc("Financing Facility", **base).insert()
    a["fac"] = approve_submit(f)
    return a


def _draw(a, amount=5_000_000, days_ago=40, fac=None):
    with session_as(MAKER):
        d = new_doc("Financing Drawdown", facility=(fac or a["fac"]).name, drawdown_date=date.today() - timedelta(days=days_ago), amount=amount, bank_account=a["bank"].name, narration="Working capital").insert()
    return approve_submit(d)


def test_drawdown_posts_builds_schedule_and_respects_the_limit(tmp_path):
    a = _world(tmp_path)
    try:
        assert a["fac"].status == "Active"
        dd = _draw(a)
        assert get_account_balance(a["bank"].name) == D("4950000")        # amount less the 1% arrangement fee
        assert get_account_balance(a["int"].name) == D("50000")            # the fee, expensed
        assert get_account_balance(a["loan"].name) == D("-5000000")
        assert len(dd.schedule) == 12 and dd.schedule[-1].closing_principal == 0
        assert round(sum(D(l.principal_due) for l in dd.schedule), 2) == D("5000000.00")
        fac = get_doc("Financing Facility", a["fac"].name)
        assert (D(fac.total_drawn), D(fac.outstanding_principal), D(fac.undrawn_available)) == (D(5000000), D(5000000), D(5000000))
        with session_as(MAKER):
            with pytest.raises(ValidationError):
                new_doc("Financing Drawdown", facility=fac.name, drawdown_date=date.today(), amount=6_000_000, bank_account=a["bank"].name).insert()
            with pytest.raises(ValidationError):                            # before the facility could be drawn
                new_doc("Financing Drawdown", facility=fac.name, drawdown_date=date.today() - timedelta(days=500), amount=1000, bank_account=a["bank"].name).insert()
    finally:
        velora.shutdown()


def test_accrual_then_repayment_with_withholding_tax_and_cancellation(tmp_path):
    a = _world(tmp_path)
    try:
        dd = _draw(a)
        through = date.today() - timedelta(days=1)
        with session_as(MAKER):
            acr = new_doc("Interest Accrual", accrual_date=through, currency="NGN", narration="Interest").insert()
        expected = D(5_000_000) * D(20) / 100 * D(40) / D(365)              # 40 days at 20% on 5m, Actual/365
        assert abs(D(acr.total_interest) - expected) < D("0.05")
        acr = approve_submit(acr)
        assert get_account_balance(a["accr"].name) == -D(acr.total_interest)
        dd2 = get_doc("Financing Drawdown", dd.name)
        assert D(dd2.accrued_interest_balance) == D(acr.total_interest) and dd2.interest_accrued_to == date.today()
        with session_as(MAKER):
            with pytest.raises(ValidationError):                            # nothing more to accrue to the same date
                new_doc("Interest Accrual", accrual_date=through, currency="NGN").insert()
        # the first instalment fell due; pay what the schedule says
        with session_as(MAKER):
            rp = new_doc("Financing Repayment", drawdown=dd.name, repayment_date=date.today(), bank_account=a["bank"].name, narration="Instalment 1").insert()
        first = dd.schedule[0]
        assert D(rp.principal_amount) == D(first.principal_due) and D(rp.interest_amount) == D(first.interest_due)
        assert D(rp.wht_amount) == (D(rp.interest_amount) * D("0.10")).quantize(D("0.01"))
        assert D(rp.net_paid) == D(rp.total_cost) - D(rp.wht_amount)
        bank_before, loan_before = get_account_balance(a["bank"].name), get_account_balance(a["loan"].name)
        rp = approve_submit(rp)
        assert get_account_balance(a["bank"].name) == bank_before - D(rp.net_paid)
        assert get_account_balance(a["loan"].name) == loan_before + D(rp.principal_amount)
        assert get_account_balance(a["whtpay"].name) == -D(rp.wht_amount)
        cleared = min(D(rp.interest_amount), D(acr.total_interest))
        assert D(rp.accrued_interest_cleared) == cleared
        assert get_account_balance(a["accr"].name) == -(D(acr.total_interest) - cleared)
        dd3 = get_doc("Financing Drawdown", dd.name)
        assert D(dd3.outstanding_principal) == D(5_000_000) - D(rp.principal_amount) and dd3.schedule[0].status == "Paid"
        from velora_erp.tax import service as tax
        y = date.today().year
        rows = [r for r in tax.ledger_rows(date(y, 1, 1), date(y, 12, 31)) if r["tax_code"] == "WHTINT"]
        assert len(rows) == 1 and rows[0]["section"] == "Output tax" and D(rows[0]["tax"]) == D(rp.wht_amount) and D(rows[0]["net"]) == D(rp.interest_amount)
        # cancelling puts everything back
        with session_as(APPROVER):
            get_doc("Financing Repayment", rp.name).cancel(ignore_permissions=True)
        assert get_account_balance(a["bank"].name) == bank_before and get_account_balance(a["whtpay"].name) == 0
        dd4 = get_doc("Financing Drawdown", dd.name)
        assert D(dd4.outstanding_principal) == D(5_000_000) and dd4.schedule[0].status == "Scheduled" and D(dd4.accrued_interest_balance) == D(acr.total_interest)
        with pytest.raises(Exception):                                      # the accrual is not the latest thing now? it is, but the drawdown still depends on it
            get_doc("Financing Drawdown", dd.name).cancel(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_covenants_amendment_repricing_and_insight(tmp_path):
    from velora_erp.treasury import insight, service as svc
    a = _world(tmp_path, interest_rate_type="Floating", reference_rate_name="MPR", rate_spread=2, interest_rate=20)
    try:
        dd = _draw(a, days_ago=10)
        before = [D(l.interest_due) for l in dd.schedule]
        with session_as(MAKER):
            am = new_doc("Facility Amendment", facility=a["fac"].name, effective_date=date.today() - timedelta(days=5), reason="MPR raised", new_interest_rate=25).insert()
        approve_submit(am)
        dd2 = get_doc("Financing Drawdown", dd.name)
        assert D(get_doc("Financing Facility", a["fac"].name).interest_rate) == D(25)
        assert sum(D(l.interest_due) for l in dd2.schedule) > sum(before)       # the higher rate reprices the unpaid instalments
        assert round(sum(D(l.principal_due) for l in dd2.schedule), 2) == D("5000000.00")
        with session_as(APPROVER):
            get_doc("Facility Amendment", am.name).cancel(ignore_permissions=True)
        assert D(get_doc("Financing Facility", a["fac"].name).interest_rate) == D(20)
        assert [D(l.interest_due) for l in get_doc("Financing Drawdown", dd.name).schedule] == before
        with session_as(MAKER):
            t1 = new_doc("Covenant Test", facility=a["fac"].name, covenant_name="Debt service cover", tested_on=date.today() - timedelta(days=2), actual_value=1.5).insert()
            t2 = new_doc("Covenant Test", facility=a["fac"].name, covenant_name="Debt service cover", tested_on=date.today() - timedelta(days=1), actual_value=1.25).insert()
            t3 = new_doc("Covenant Test", facility=a["fac"].name, covenant_name="Debt service cover", tested_on=date.today(), actual_value=1.1).insert()
            with pytest.raises(ValidationError):
                new_doc("Covenant Test", facility=a["fac"].name, covenant_name="Not a covenant", tested_on=date.today(), actual_value=1).insert()
        assert (t1.status, t2.status, t3.status) == ("Compliant", "Warning", "Breach")
        with session_as(APPROVER):
            d = insight.dashboard()
            finds = " | ".join(f["title"] for f in d["findings"])
            assert D(d["total_debt"]) == D(5_000_000) and d["loans"] == 1 and d["covenants"].get("Breach") == 1
            assert "breached" in finds
            lq = insight.liquidity()
            assert len(lq["rows"]) == 13 and lq["opening"] == D("4950000")
            assert insight.fx_exposure() == [] and len(insight.portfolio()) == 1
    finally:
        velora.shutdown()


def test_every_treasury_report_runs_on_an_empty_and_a_populated_book(tmp_path):
    from velora_erp.treasury import reports
    a = _world(tmp_path)
    try:
        def run_all(dd=None):
            for name in reports.BUILDERS:
                flt = {"drawdown": dd} if name == "Loan Amortisation Schedule" else {}
                if name == "Loan Amortisation Schedule" and not dd:
                    with pytest.raises(ValidationError):
                        reports.run(name, flt)
                    continue
                rb = reports.run(name, flt)
                assert rb is not None, name
        with session_as(APPROVER):
            run_all()
            dd = _draw(a)
            run_all(dd.name)
            rows = reports.portfolio({})[1]
            assert len(rows) == 1 and rows[0]["outstanding"] == 5_000_000.0 and rows[0]["rate"] == 20.0
            sched = reports.service_schedule({})[1]
            assert len(sched) == 12 and round(sum(r["principal"] for r in sched), 2) == 5_000_000.0
            with pytest.raises(ValidationError):
                reports.service_schedule({"from_date": "2026-02-01", "to_date": "2026-01-01"})
            assert sum(r["principal"] for r in reports.ladder({})[1]) > 0
            with pytest.raises(ValidationError):
                reports.run("Tax Ledger", {})
    finally:
        velora.shutdown()


def test_the_daily_job_refreshes_and_drafts_the_month_end_accrual_without_posting(tmp_path):
    from velora_erp.treasury import jobs
    a = _world(tmp_path)
    try:
        _draw(a, days_ago=60)
        first = date.today().replace(day=2)                                  # inside the first days of a month
        with session_as(APPROVER):
            out = jobs.daily(first)
            assert len(out["accruals"]) == 1
            assert get_account_balance(a["accr"].name) == 0                  # a draft: nothing is posted
            assert jobs.daily(first)["accruals"] == []                       # and it is not drafted twice
            assert jobs.daily(date.today().replace(day=20))["accruals"] == []
    finally:
        velora.shutdown()
