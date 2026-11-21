"""Account > Allow Reconciliation is a real, editable setting: it starts from the Account Type, follows a change of type,
can be switched off for one account, and a Bank Account cannot sit on an account that does not allow reconciliation."""
import pytest
import velora
from velora import get_doc, new_doc
from velora.exceptions import ValidationError

from test_cash_transactions import setup_cash


def _bank(account, code="B1"):
    return new_doc("Bank Account", account_code=code, account_name="Main", bank_name="Acme Bank", account_number="0123456789",
                   gl_account=account.name, currency="NGN")


def test_allow_reconciliation_starts_from_the_account_type_and_is_the_users_choice_after(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        bank = accounts["1000"]
        assert bank.reconciliation_required == 1                                    # BANK allows reconciliation by default
        expense = accounts["5000"]
        assert expense.reconciliation_required == 0                                 # OPERATING_EXPENSE does not
        bank.reconciliation_required = 0; bank.save(ignore_permissions=True)
        assert get_doc("Account", bank.name).reconciliation_required == 0           # the choice sticks across saves
        again = get_doc("Account", bank.name); again.account_name = "Main Bank (renamed)"; again.save(ignore_permissions=True)
        assert get_doc("Account", bank.name).reconciliation_required == 0
    finally:
        velora.shutdown()


def test_changing_the_account_type_takes_the_new_types_default(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        a = new_doc("Account", account_code="1900", account_name="Parking", account_group="A", account_type="CLEARING", allow_manual_posting=1).insert(ignore_permissions=True)
        before = a.reconciliation_required
        a.account_type = "BANK"; a.save(ignore_permissions=True)
        assert get_doc("Account", a.name).reconciliation_required == 1
    finally:
        velora.shutdown()


def test_a_bank_account_needs_a_gl_account_that_allows_reconciliation(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        gl = accounts["1000"]
        gl.reconciliation_required = 0; gl.save(ignore_permissions=True)
        with pytest.raises(ValidationError, match="does not allow reconciliation"):
            _bank(gl).insert(ignore_permissions=True)
        gl.reconciliation_required = 1; gl.save(ignore_permissions=True)
        assert _bank(gl).insert(ignore_permissions=True).name
    finally:
        velora.shutdown()
