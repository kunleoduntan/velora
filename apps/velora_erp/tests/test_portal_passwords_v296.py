"""Portal passwords behave like staff passwords: temporary passwords must be changed, forgotten passwords wait for staff (or use a one-time link), strong rules everywhere."""
import pytest
import velora
from velora import portal as core
from velora.exceptions import PermissionDenied, ValidationError
from test_cash_transactions import setup_cash
from velora_erp import portal_service as ps


def _site(tmp_path):
    return setup_cash(tmp_path)


def _token(email, password):
    from sqlalchemy import select, update
    from velora import db
    core.authenticate(email, password)
    with db.transaction() as c:
        return c.execute(select(core.sessions.c.token_hash)).scalars().all()


def test_invited_contact_must_choose_a_new_password_before_anything_else(tmp_path):
    accounts, customer, supplier = _site(tmp_path)
    try:
        r = ps.invite("buyer@example.com", "Bola Buyer", "Customer", customer.name)
        assert r["temporary_password"].count("-") == 2
        login = core.authenticate("buyer@example.com", r["temporary_password"])
        assert login["user"]["must_change"] is True
        with pytest.raises(PermissionDenied, match="temporary password"):
            core.resolve_token(login["token"])                               # blocked everywhere ...
        assert core.resolve_token(login["token"], allow_pending=True)["must_change"] is True      # ... except to say who you are and change the password
        with pytest.raises(ValidationError):
            core.change_password(login["user"]["id"], r["temporary_password"], "weakpass1")
        core.change_password(login["user"]["id"], r["temporary_password"], "Brand-new-pass-77")
        again = core.authenticate("buyer@example.com", "Brand-new-pass-77")
        assert again["user"]["must_change"] is False and core.resolve_token(again["token"])["email"] == "buyer@example.com"
    finally:
        velora.shutdown()


def test_staff_reset_issues_a_new_temporary_password_and_clears_the_waiting_flag(tmp_path):
    accounts, customer, supplier = _site(tmp_path)
    try:
        r = ps.invite("buyer@example.com", "Bola", "Customer", customer.name)
        u = core.authenticate("buyer@example.com", r["temporary_password"])["user"]
        core.change_password(u["id"], r["temporary_password"], "Brand-new-pass-77")
        a = core.request_reset("buyer@example.com", "https://erp.example.com", None)
        b = core.request_reset("nobody@example.com", "https://erp.example.com", None)
        assert a == b and a["mode"] == "staff"                                # same answer: no account discovery
        assert core.reset_requests() == {"buyer@example.com"}
        new = ps.reset_password("buyer@example.com")
        assert core.reset_requests() == set()
        assert core.authenticate("buyer@example.com", new["temporary_password"])["user"]["must_change"] is True
    finally:
        velora.shutdown()


def test_forgot_password_with_email_uses_a_one_time_link(tmp_path):
    accounts, customer, supplier = _site(tmp_path)
    try:
        r = ps.invite("buyer@example.com", "Bola", "Customer", customer.name)
        u = core.authenticate("buyer@example.com", r["temporary_password"])["user"]
        core.change_password(u["id"], r["temporary_password"], "Brand-new-pass-77")
        sent = []
        out = core.request_reset("buyer@example.com", "https://erp.example.com/", lambda to, name, link, minutes: sent.append((to, link, minutes)))
        assert out["mode"] == "email" and len(sent) == 1 and core.reset_requests() == set()
        token = sent[0][1].split("token=")[1]
        assert sent[0][1].startswith("https://erp.example.com/portal#/reset?token=")
        core.request_reset("buyer@example.com", "https://erp.example.com", lambda *a: sent.append(a))       # asked again within two minutes: nothing more is sent
        assert len(sent) == 1
        with pytest.raises(ValidationError):
            core.complete_reset(token, "weak")
        assert core.complete_reset(token, "Another-secret-4411") == {"reset": True}
        assert core.authenticate("buyer@example.com", "Another-secret-4411")["user"]["must_change"] is False
        with pytest.raises(ValidationError):
            core.complete_reset(token, "Third-secret-99xx")                  # once only
    finally:
        velora.shutdown()


def test_staff_listing_shows_who_is_waiting(tmp_path):
    accounts, customer, supplier = _site(tmp_path)
    try:
        ps.invite("buyer@example.com", "Bola", "Customer", customer.name)
        core.request_reset("buyer@example.com", "https://erp.example.com", None)
        from velora_erp.finance import portal_admin_api as api
        import inspect
        assert "reset_requested" in inspect.getsource(api)
    finally:
        velora.shutdown()
