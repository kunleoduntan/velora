from datetime import date
import pytest, velora
from velora import new_doc, get_doc
from velora.permissions import Session, session_as, filter_dict
from velora_erp.setup import after_install
from velora_erp.hr.data_protection import apply_default_field_protection


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'dp.db'}", apps=["velora_erp"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield
    velora.shutdown()


def test_finance_and_audit_roles_do_not_see_identity_or_bank_data_but_hr_does(site):
    e = new_doc("Employee", employee_code="E1", employee_name="E1", employee_type="Permanent", date_of_joining=date(2020, 1, 1),
                tax_id="TIN123", bank_account_no="0123456789", date_of_birth=date(1990, 1, 1)).insert(ignore_permissions=True)
    row = get_doc("Employee", e.name, ignore_permissions=True).as_dict()
    seen = filter_dict("Employee", row, Session(user="aud", roles=frozenset({"Auditor"})))
    assert "tax_id" not in seen and "bank_account_no" not in seen and "date_of_birth" not in seen and seen["employee_name"] == "E1"
    pay = filter_dict("Employee", row, Session(user="pay", roles=frozenset({"Payroll Officer"})))
    assert "bank_account_no" in pay and "tax_id" in pay and "date_of_birth" not in pay      # payroll still pays and deducts tax
    hr = filter_dict("Employee", row, Session(user="hr", roles=frozenset({"HR Manager"})))
    assert hr["tax_id"] == "TIN123" and hr["bank_account_no"] == "0123456789"


def test_installing_twice_never_overrides_an_administrators_choice(site):
    assert apply_default_field_protection() == 0
