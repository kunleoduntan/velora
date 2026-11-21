"""Richer Employee master (photo, reporting line, statutory/bank details) and Account controls (frozen, cost centre required)."""
from datetime import date, timedelta
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from test_cash_transactions import setup_cash, approve, MAKER

ADMIN = Session(user="Administrator", roles=frozenset({"System Manager"}))


def test_employee_details_reporting_line_and_photo(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        meta = velora.meta.registry.get("Employee")
        assert meta.image_field == "photo" and meta.to_dict()["image_field"] == "photo"
        boss = new_doc("Employee", employee_code="E-BOSS", first_name="Ada", last_name="Obi", employee_type="Permanent", date_of_joining=date(2020, 1, 1)).insert(ignore_permissions=True)
        assert boss.employee_name == "Ada Obi", "the full name is built from first/last when left blank"
        emp = new_doc("Employee", employee_code="E-1", employee_name="Tunde Bello", employee_type="Permanent", reports_to=boss.name, gender="Male", date_of_birth=date(1990, 5, 1),
                      date_of_joining=date(2022, 3, 1), pension_pin="PEN100", tax_id="TIN-1", salary_mode="Bank", bank_name="GTBank", bank_account_no="0123456789").insert(ignore_permissions=True)
        assert emp.employment_status == "Active"
        boss = get_doc("Employee", boss.name, ignore_permissions=True); boss.reports_to = emp.name
        with pytest.raises(ValidationError, match="loop"):
            boss.save(ignore_permissions=True)
        emp = get_doc("Employee", emp.name, ignore_permissions=True); emp.date_of_birth = date(2023, 1, 1)
        with pytest.raises(ValidationError, match="after the Date of Birth"):
            emp.save(ignore_permissions=True)
        emp = get_doc("Employee", emp.name, ignore_permissions=True); emp.employment_status = "Left"
        with pytest.raises(ValidationError, match="Relieving Date"):
            emp.save(ignore_permissions=True)
        # the photo must be an image attached to this employee
        from velora.files import add_attachment
        with session_as(ADMIN):
            doc_file = add_attachment(b"%PDF-1.4 x", "cv.pdf", doctype="Employee", docname=emp.name, content_type="application/pdf")
            img = add_attachment(b"\x89PNG\r\n\x1a\n0000", "me.png", doctype="Employee", docname=emp.name, content_type="image/png")
            emp = get_doc("Employee", emp.name, ignore_permissions=True); emp.employment_status = "Active"; emp.photo = doc_file["id"]
            with pytest.raises(ValidationError, match="image attached"):
                emp.save(ignore_permissions=True)
            emp = get_doc("Employee", emp.name, ignore_permissions=True); emp.photo = img["id"]; emp.save(ignore_permissions=True)
        assert get_doc("Employee", emp.name, ignore_permissions=True).photo == img["id"]
    finally:
        velora.shutdown()


def test_frozen_and_cost_centre_required_accounts(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        acct = get_doc("Account", accounts["5000"].name, ignore_permissions=True)
        assert acct.report_type == "Profit and Loss"
        assert get_doc("Account", accounts["1000"].name, ignore_permissions=True).report_type == "Balance Sheet"
        acct.requires_cost_centre = 1; acct.save(ignore_permissions=True)
        cc = new_doc("Cost Centre", cost_centre_code="ADM", cost_centre_name="Admin").insert(ignore_permissions=True)
        def pay(**extra):
            line = {"account": accounts["5000"].name, "amount": 100, "description": "x", **extra}
            return new_doc("Payment", payment_date=date.today(), posting_date=date.today(), purpose="Expense Payment", currency="NGN", exchange_rate=1,
                           cash_account=accounts["1000"].name, narration="Office", beneficiary="Landlord", lines=[line]).insert(ignore_permissions=True)
        with session_as(MAKER):
            p = pay()
        with pytest.raises(Exception, match="requires a Cost Centre"):
            approve(p)
        with session_as(MAKER):
            p = pay(cost_centre=cc.name)
        approve(p)
        acct = get_doc("Account", accounts["5000"].name, ignore_permissions=True); acct.frozen = 1; acct.save(ignore_permissions=True)
        with session_as(MAKER):
            p2 = pay(cost_centre=cc.name)
        with pytest.raises(Exception, match="frozen"):
            approve(p2)
    finally:
        velora.shutdown()
