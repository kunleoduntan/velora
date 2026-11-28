from datetime import date, timedelta
import pytest
import velora
from velora import new_doc
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import session_as, Session
from test_cash_transactions import setup_cash, MAKER
from test_invoice_settlement_v271 import _sales_invoice, _purchase_invoice
from velora import portal as core
from velora_erp import portal_service as ps

T = date.today()


def _login(email, password):
    return core.authenticate(email, password)["user"]


def test_invite_returns_a_one_time_password_that_works_and_reset_replaces_it(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        r = ps.invite("Buyer@Example.com", "Bola Buyer", "Customer", customer.name)
        assert r["email"] == "buyer@example.com" and len(r["temporary_password"]) >= 10
        assert _login(r["email"], r["temporary_password"])["roles"] == ["Customer Portal"]
        again = ps.reset_password("buyer@example.com")
        with pytest.raises(PermissionDenied):
            _login(r["email"], r["temporary_password"])
        _login(r["email"], again["temporary_password"])
        with pytest.raises(ValidationError):
            ps.invite("buyer@example.com", "Dup", "Customer", customer.name)
        with pytest.raises(ValidationError, match="does not exist"):
            ps.invite("ghost@example.com", "Ghost", "Customer", "NOPE")
    finally:
        velora.shutdown()


def test_a_contact_only_ever_sees_their_own_party(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        other = new_doc("Customer", customer_code="C002", customer_name="Other Ltd", customer_group=customer.customer_group, customer_type="Company",
                        control_account=customer.control_account, advance_account=customer.advance_account).insert(ignore_permissions=True)
        mine = _sales_invoice(accounts, customer, 1000, narration="Mine")
        ps.invite("buyer@example.com", "Bola", "Customer", customer.name)
        ps.invite("seller@example.com", "Sade", "Supplier", supplier.name)
        _purchase_invoice(accounts, supplier, 700)
        buyer = _login_user("buyer@example.com")
        data = ps.customer_invoices(buyer, {})["items"]
        assert [r["name"] for r in data] == [mine.name] and data[0]["outstanding"] == 1000 and data[0]["state"] in ("Open",)
        ov = ps.customer_overview(buyer, {})
        assert ov["summary"]["open_invoices"] == 1 and float(ov["summary"]["by_currency"][0]["outstanding"]) == 1000
        # a customer cannot use supplier providers, and a supplier cannot use customer providers
        with pytest.raises(PermissionDenied):
            ps.supplier_invoices(buyer, {})
        seller = _login_user("seller@example.com")
        with pytest.raises(PermissionDenied):
            ps.customer_invoices(seller, {})
        assert len(ps.supplier_invoices(seller, {})["items"]) == 1
        theirs = _sales_invoice(accounts, other, 5, narration="Theirs")          # another customer's invoice never appears
        assert [r["name"] for r in ps.customer_invoices(buyer, {})["items"]] == [mine.name]
        assert theirs.name not in [r["name"] for r in ps.customer_invoices(buyer, {})["items"]]
    finally:
        velora.shutdown()


def _login_user(email):
    return core.resolve_token(_token_for(email), allow_pending=True)


_PASSWORDS = {}


def _token_for(email):
    pw = ps.reset_password(email)["temporary_password"]
    return core.authenticate(email, pw)["token"]


def test_suspended_or_unlinked_accounts_are_refused(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        ps.invite("buyer@example.com", "Bola", "Customer", customer.name)
        token = _token_for("buyer@example.com")
        user = core.resolve_token(token, allow_pending=True)
        ps.set_status("buyer@example.com", "Suspended")
        with pytest.raises(PermissionDenied):
            core.resolve_token(token, allow_pending=True)                                   # the open session ends the moment the contact is suspended
        with pytest.raises(PermissionDenied):
            ps.customer_overview({"email": "buyer@example.com", "roles": ["Customer Portal"]}, {})
        ps.set_status("buyer@example.com", "Active")
        ps.customer_overview(user, {})
        with pytest.raises(PermissionDenied):
            ps.customer_overview({"email": "stranger@example.com", "roles": ["Customer Portal"]}, {})
    finally:
        velora.shutdown()


def test_complaint_can_be_raised_only_against_own_invoice(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 1000)
        ps.invite("buyer@example.com", "Bola", "Customer", customer.name)
        buyer = _login_user("buyer@example.com")
        made = ps.customer_complaint_create(buyer, {"category": "Late Delivery", "description": "Arrived a week late", "sales_invoice": inv.name})
        assert made["resolution_status"] == "Open"
        rows = ps.customer_complaints(buyer, {})["items"]
        assert [r["name"] for r in rows] == [made["name"]]
        with pytest.raises(ValidationError):
            ps.customer_complaint_create(buyer, {"category": "Nonsense", "description": "x"})
        with pytest.raises(ValidationError, match="not on your account"):
            ps.customer_complaint_create(buyer, {"category": "Service", "description": "x", "sales_invoice": "SI-DOES-NOT-EXIST"})
    finally:
        velora.shutdown()


def test_five_wrong_passwords_lock_the_sign_in_for_a_while(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        r = ps.invite("buyer@example.com", "Bola", "Customer", customer.name)
        core._FAILS.clear()
        for _ in range(core.MAX_FAILS):
            with pytest.raises(PermissionDenied, match="Invalid"):
                core.authenticate("buyer@example.com", "wrong-password-1")
        with pytest.raises(PermissionDenied, match="Too many"):
            core.authenticate("buyer@example.com", r["temporary_password"])          # even the right password waits
        core._FAILS.clear()
        assert core.authenticate("buyer@example.com", r["temporary_password"])["user"]["email"] == "buyer@example.com"
    finally:
        core._FAILS.clear()
        velora.shutdown()
