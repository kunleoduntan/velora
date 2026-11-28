"""IFRS 9 expected credit loss allowance and IAS 37 provisions."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as

from test_cash_transactions import MAKER, approve, setup_cash
from velora_erp.finance.engine import get_account_balance

D = Decimal
FM = MAKER.__class__("fin@example.test", frozenset({"Finance Manager"}))


def _acct(code, name, typ, root):
    grp = get_list("Account Group", filters={"root_type": root}, fields=["name"], limit=1)[0]["name"]
    return new_doc("Account", account_code=code, account_name=name, account_group=grp, account_type=typ, allow_manual_posting=1).insert(ignore_permissions=True)


def _invoice(a, c, amount, days_overdue):
    due = date.today() - timedelta(days=days_overdue)
    with session_as(MAKER):
        inv = new_doc("Sales Invoice", invoice_date=due, posting_date=due, due_date=due, party=c.name, currency=_base(), exchange_rate=1, narration="x",
                      lines=[{"account": a["4000"].name, "description": "s", "amount": amount}]).insert()
    return approve(inv)


def _base():
    from velora_erp.finance.source_documents import finance_settings
    return finance_settings()["base_currency"]


def _assess(exp, allow, rates):
    with session_as(MAKER):
        r = new_doc("Expected Credit Loss Assessment", assessment_date=date.today(), expense_account=exp.name, allowance_account=allow.name,
                    bands=[{"bucket": b, "loss_rate": v} for b, v in rates.items()]).insert()
    return r


def test_ecl_charge_then_release_posts_only_the_change(tmp_path):
    a, c, s = setup_cash(tmp_path)
    try:
        exp, allow = _acct("5900", "Impairment loss", "OPERATING_EXPENSE", "Expense"), _acct("1190", "Loss allowance", "LOSS_ALLOWANCE", "Asset")
        _invoice(a, c, 1000, 0), _invoice(a, c, 2000, 45), _invoice(a, c, 4000, 120)
        r = _assess(exp, allow, {"Not Due": 1, "31-60 Days": 10, "Over 90 Days": 50})
        assert D(r.total_exposure) == 7000 and D(r.required_allowance) == D(10) + D(200) + D(2000) and D(r.adjustment) == 2210
        r = approve(r)
        assert get_account_balance(exp.name) == 2210 and get_account_balance(allow.name) == -2210
        # the same matrix again: nothing to post
        with pytest.raises(ValidationError):
            _assess(exp, allow, {"Not Due": 1, "31-60 Days": 10, "Over 90 Days": 50})
        # a cheaper matrix releases the difference only
        r2 = approve(_assess(exp, allow, {"Over 90 Days": 50}))
        assert D(r2.adjustment) == -210 and get_account_balance(allow.name) == -2000 and get_account_balance(exp.name) == 2000
        with session_as(FM):
            get_doc("Expected Credit Loss Assessment", r2.name).cancel(ignore_permissions=True)
        assert get_account_balance(allow.name) == -2210
    finally:
        velora.shutdown()


def test_provision_needs_criteria_and_cannot_be_overused(tmp_path):
    a, c, s = setup_cash(tmp_path)
    try:
        exp, prov = _acct("5910", "Provision expense", "OPERATING_EXPENSE", "Expense"), _acct("2900", "Legal provision", "PROVISION", "Liability")

        def entry(kind, amount, ok=True):
            with session_as(MAKER):
                return new_doc("Provision Entry", entry_date=date.today(), entry_type=kind, description="Claim", provision_account=prov.name, counter_account=exp.name if kind in ("Recognise", "Increase", "Unwind discount") else a["1000"].name,
                               amount=amount, present_obligation=ok, probable_outflow=ok, reliable_estimate=ok).insert()
        with pytest.raises(ValidationError):
            entry("Recognise", 500, ok=False)
        approve(entry("Recognise", 500))
        assert get_account_balance(prov.name) == -500 and get_account_balance(exp.name) == 500
        with pytest.raises(ValidationError):
            entry("Utilise", 600)
        approve(entry("Utilise", 200))
        assert get_account_balance(prov.name) == -300
        approve(entry("Unwind discount", 20, ok=True))
        assert get_account_balance(prov.name) == -320
    finally:
        velora.shutdown()
