"""Tax Journal: withholding tax from customers and suppliers, invoice settlement, cancellation."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as

from test_invoices_v08 import MAKER, approve_submit, setup
from test_tax_management import _rule
from velora_erp.finance.engine import get_account_balance

D = Decimal


def _invoices(a):
    with session_as(MAKER):
        s = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="s",
                    lines=[{"account": a["rev"].name, "description": "Consulting", "amount": 1000}]).insert()
        p = new_doc("Purchase Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["supp"].name, currency="NGN", exchange_rate=1, narration="p",
                    lines=[{"account": a["exp"].name, "description": "Supplies", "amount": 2000}]).insert()
    return approve_submit(s), approve_submit(p)


def _journal(a, s, p, **over):
    rows = [{"party_type": "Customer", "party": a["cust"].name, "invoice_reference": s.name, "gross_amount": 1000, "tax_rule": "WHT5C"},
            {"party_type": "Supplier", "party": a["supp"].name, "invoice_reference": p.name, "gross_amount": 2000, "tax_rule": "WHT10S"}]
    doc = dict(title="WHT", posting_date=date.today(), currency="NGN", exchange_rate=1, narration="withholding", lines=rows)
    doc.update(over)
    with session_as(MAKER):
        return new_doc("Tax Journal", **doc).insert()


def test_customer_and_supplier_wht_post_settle_and_cancel(tmp_path):
    a = setup(tmp_path)
    try:
        _rule(a, "WHT5C", 5, a["vatin"].name, tax_type="WHT")
        _rule(a, "WHT10S", 10, a["vatout"].name, tax_type="WHT")
        s, p = _invoices(a)
        ar_before, ap_before = get_account_balance(a["ar"].name), get_account_balance(a["ap"].name)
        tj = _journal(a, s, p)
        assert (D(tj.total_suffered), D(tj.total_payable)) == (D("50"), D("200"))
        tj = approve_submit(tj)
        assert get_account_balance(a["vatin"].name) == D("50")          # WHT credit receivable (asset)
        assert get_account_balance(a["vatout"].name) == D("-200")       # WHT payable (liability)
        assert get_account_balance(a["ar"].name) == ar_before - D("50")
        assert get_account_balance(a["ap"].name) == ap_before + D("200")
        assert D(get_doc("Sales Invoice", s.name).amount_settled) == D("50")
        assert D(get_doc("Purchase Invoice", p.name).amount_settled) == D("200")
        from velora_erp.tax import service as tax
        rows = tax.ledger_rows(date(date.today().year, 1, 1), date(date.today().year, 12, 31))
        assert sorted((r["section"], r["tax_code"], r["tax"]) for r in rows) == [("Input tax", "WHT5C", D("50")), ("Output tax", "WHT10S", D("200"))]
        tj.cancel()
        assert get_account_balance(a["vatin"].name) == 0 and get_account_balance(a["ar"].name) == ar_before
        assert D(get_doc("Sales Invoice", s.name).amount_settled) == 0
    finally:
        velora.shutdown()


def test_wrong_account_side_over_settlement_and_missing_rule_are_refused(tmp_path):
    a = setup(tmp_path)
    try:
        _rule(a, "WHT5C", 5, a["vatout"].name, tax_type="WHT")       # liability account on a customer row
        _rule(a, "WHT10S", 10, a["vatout"].name, tax_type="WHT")
        s, p = _invoices(a)
        with pytest.raises(ValidationError, match="asset account"):
            _journal(a, s, p)
        with pytest.raises(ValidationError, match="no approved WHT rule"):
            _journal(a, s, p, lines=[{"party_type": "Customer", "party": a["cust"].name, "gross_amount": 100, "tax_rule": "NOPE", "tax_account": a["vatin"].name}])
        with pytest.raises(ValidationError, match="outstanding"):
            _journal(a, s, p, lines=[{"party_type": "Customer", "party": a["cust"].name, "invoice_reference": s.name, "gross_amount": 5000, "wht_amount": 2000, "tax_account": a["vatin"].name}])
        with pytest.raises(ValidationError, match="not a submitted invoice"):
            _journal(a, s, p, lines=[{"party_type": "Supplier", "party": a["supp"].name, "invoice_reference": s.name, "gross_amount": 100, "wht_amount": 10, "tax_account": a["vatout"].name}])
    finally:
        velora.shutdown()


def test_company_income_tax_computation_uses_account_flags_losses_levy_and_wht_credit(tmp_path):
    from velora_erp.tax import cit
    a = setup(tmp_path)
    try:
        _rule(a, "CIT30", 30, None, tax_type="Income Tax")
        _rule(a, "DEVLEVY", 4, None, tax_type="Levy")
        _rule(a, "WHT5C", 5, a["vatin"].name, tax_type="WHT")
        acc = get_doc("Account", a["exp"].name)
        acc.tax_treatment, acc.disallowed_percent = "Partly allowable", 50
        acc.save()
        with session_as(MAKER):
            s = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["cust"].name, currency="NGN", exchange_rate=1, narration="s",
                        lines=[{"account": a["rev"].name, "description": "Consulting", "amount": 5000}]).insert()
            p = new_doc("Purchase Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=a["supp"].name, currency="NGN", exchange_rate=1, narration="p",
                        lines=[{"account": a["exp"].name, "description": "Supplies", "amount": 2000}]).insert()
        s, p = approve_submit(s), approve_submit(p)
        with session_as(MAKER):
            approve_submit(new_doc("Tax Journal", title="w", posting_date=date.today(), currency="NGN", exchange_rate=1, narration="n",
                                   lines=[{"party_type": "Customer", "party": a["cust"].name, "invoice_reference": s.name, "gross_amount": 2000, "tax_rule": "WHT5C"}]).insert())
        jur = get_list("Tax Jurisdiction", fields=["name"])[0]["name"]
        y = date.today().year
        c = new_doc("Income Tax Computation", title="CIT", jurisdiction=jur, period_start=date(y, 1, 1), period_end=date(y, 12, 31), income_tax_rule="cit30", levy_rules="devlevy",
                    loss_brought_forward=500).insert(ignore_permissions=True)
        out = cit.calculate_computation(c.name)
        v = {k: D(x) for k, x in out.items() if k != "name"}
        assert (v["accounting_profit"], v["total_add_backs"], v["adjusted_profit"], v["loss_relieved"], v["assessable_profit"]) == (D(3000), D(1000), D(4000), D(500), D(3500))
        assert (v["income_tax"], v["levies"], v["wht_available"], v["wht_utilised"], v["net_payable"]) == (D(1050), D(140), D(100), D(100), D(1090))
        sub = approve_submit(get_doc("Income Tax Computation", c.name))
        assert sub.docstatus == 1
        # the next period starts with the loss position of this one
        assert cit.previous_loss(jur, date(y + 1, 1, 1)) == 0
    finally:
        velora.shutdown()


def test_new_reports_adviser_and_dashboard_run(tmp_path):
    from velora_erp.tax import adviser
    from velora_erp.tax.report.income_tax_computation_summary.income_tax_computation_summary import execute as cit_summary
    from velora_erp.tax.report.tax_treatment_of_accounts.tax_treatment_of_accounts import execute as treat
    from velora_erp.tax.report.wht_position_by_party.wht_position_by_party import execute as pos
    from velora_erp.tax.report.wht_register.wht_register import execute as reg
    a = setup(tmp_path)
    try:
        _rule(a, "WHT5C", 5, a["vatin"].name, tax_type="WHT")
        _rule(a, "WHT10S", 10, a["vatout"].name, tax_type="WHT")
        s, p = _invoices(a)
        approve_submit(_journal(a, s, p))
        y = date.today().year
        rng = {"from_date": date(y, 1, 1), "to_date": date(y, 12, 31)}
        reg_, pos_ = reg({**rng}), pos({**rng})
        assert reg_ is not None and pos_ is not None and reg({**rng, "missing_certificate": 1}) is not None
        assert treat(rng) is not None and cit_summary({}) is not None
        with session_as(MAKER):
            found = adviser.findings()
        titles = " ".join(f["title"] for f in found)
        assert "No approved VAT rule" in titles and "No approved Income Tax rule" in titles and "without a certificate" in titles
        d = adviser.dashboard()
        assert D(d["wht_payable"]) == D("200") and D(d["wht_credit"]) == D("50") and d["findings"]["warning"] >= 3
    finally:
        velora.shutdown()


def test_dividend_and_interest_wht_deadlines_exposure_and_reminders(tmp_path):
    from velora_erp.tax import adviser, deadlines
    a = setup(tmp_path)
    try:
        _rule(a, "WHT10D", 10, a["vatin"].name, tax_type="WHT")
        _rule(a, "WHT10P", 10, a["vatout"].name, tax_type="WHT")
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="counter account"):
                new_doc("Tax Journal", title="d", posting_date=date.today(), currency="NGN", exchange_rate=1, narration="n",
                        lines=[{"party_type": "Income received", "party_name": "ABC Plc", "nature": "Dividend", "gross_amount": 1000, "tax_rule": "WHT10D"}]).insert()
            tj = new_doc("Tax Journal", title="d", posting_date=date.today() - timedelta(days=45), currency="NGN", exchange_rate=1, narration="dividends",
                         lines=[{"party_type": "Income received", "party_name": "ABC Plc", "nature": "Dividend", "payee_class": "Corporate", "gross_amount": 1000, "tax_rule": "WHT10D", "counter_account": a["rev"].name},
                                {"party_type": "Payment made", "party_name": "Shareholder A", "nature": "Dividend", "payee_class": "Individual", "gross_amount": 3000, "tax_rule": "WHT10P", "counter_account": a["exp"].name}]).insert()
        assert (D(tj.total_suffered), D(tj.total_payable)) == (D(100), D(300))
        approve_submit(tj)
        assert get_account_balance(a["vatin"].name) == D(100) and get_account_balance(a["vatout"].name) == D(-300)
        # deadlines come from the day in Tax Settings
        new_doc("Tax Settings", settings_name="Tax Settings", wht_remittance_day=10, late_penalty_flat=500, late_penalty_monthly_percent=2, late_interest_annual_percent=10).insert(ignore_permissions=True)
        today = date.today()
        made = deadlines.ensure_obligations(today, months=3)
        obs = get_list("Tax Obligation", filters=[["tax_type", "=", "WHT"]], fields=["name", "due_date", "period_start", "period_end", "jurisdiction", "tax_type"])
        assert made == len(obs) >= 1 and deadlines.ensure_obligations(today, months=3) == 0
        late = next(o for o in obs if date.fromisoformat(str(o["due_date"])[:10]) < today) if any(date.fromisoformat(str(o["due_date"])[:10]) < today for o in obs) else None
        assert late is not None
        ex = deadlines.exposure(late, today)
        assert ex["tax"] == D(300) and ex["penalty"] >= D(500) and ex["interest"] > 0
        assert D(adviser.dashboard()["exposure"]) > 0
        assert any("overdue" in f["title"] for f in adviser.findings())
        assert deadlines.remind(today) >= 0
    finally:
        velora.shutdown()
