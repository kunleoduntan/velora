"""Employee portal, messages received and email preferences."""
from datetime import date, timedelta
import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import PermissionDenied
from test_cash_transactions import setup_cash
from test_portal_v281 import _login_user
from velora_erp import portal_service as ps
from velora_erp.engagement import service as eng

T = date.today()


def _emp(code, first, **kw):
    return new_doc("Employee", employee_code=code, first_name=first, last_name="Bello", employee_type="Permanent", email=f"{first.lower()}@x.com", date_of_joining=kw.pop("joined", date(2020, 1, 1)), **kw).insert(ignore_permissions=True)


def test_employee_sees_only_their_own_records(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        a, b = _emp("E-1", "Tunde", date_of_birth=date(1990, 5, 1)), _emp("E-2", "Sade")
        ps.invite("tunde@x.com", "Tunde Bello", "Employee", a.name)
        ps.invite("buyer@example.com", "Bola", "Customer", customer.name)
        me = _login_user("tunde@x.com")
        ov = ps.employee_overview(me, {})
        assert ov["profile"]["employee_name"] == "Tunde BELLO" and ov["profile"]["code"] == a.name and "date_of_birth" not in ov["profile"] and ov["profile"]["service_years"] >= 5
        assert ps.employee_payslips(me, {})["items"] == [] and ps.employee_leave(me, {})["items"] == []
        # a customer cannot use employee providers, and an employee cannot use customer providers
        with pytest.raises(PermissionDenied):
            ps.employee_overview(_login_user("buyer@example.com"), {})
        with pytest.raises(PermissionDenied):
            ps.customer_invoices(me, {})
        with pytest.raises(Exception, match="does not exist"):
            ps.invite("ghost@x.com", "Ghost", "Employee", "NOPE")
    finally:
        velora.shutdown()


def test_holidays_and_celebrations_are_safe_to_show(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        soon = T + timedelta(days=5)
        a = _emp("E-1", "Tunde", date_of_birth=date(1990, soon.month, soon.day))
        _emp("E-2", "Sade", joined=date(T.year - 3, (T + timedelta(days=9)).month, (T + timedelta(days=9)).day))
        new_doc("Holiday List", holiday_list_name="Year", year=T.year, holiday_dates=[(T + timedelta(days=20)).isoformat(), (T - timedelta(days=20)).isoformat()]).insert(ignore_permissions=True)
        ps.invite("tunde@x.com", "Tunde Bello", "Employee", a.name)
        me = _login_user("tunde@x.com")
        days = ps.employee_holidays(me, {})["items"]
        assert [d["date"] for d in days] == [(T + timedelta(days=20)).isoformat()]                # the past is hidden
        cel = ps.employee_celebrations(me, {})["items"]
        assert {(c["kind"], c["first_name"]) for c in cel} >= {("Birthday", "Tunde"), ("Work Anniversary", "Sade")}
        assert all(set(c) == {"date", "kind", "first_name", "years"} for c in cel)               # first names and dates only
    finally:
        velora.shutdown()


@pytest.fixture
def notify_site(tmp_path, monkeypatch):
    real = velora.configure
    monkeypatch.setattr(velora, "configure", lambda **kw: real(**{**kw, "apps": kw["apps"] + ["velora_notify"]}))
    accounts, customer, supplier = setup_cash(tmp_path)
    c = get_doc("Customer", customer.name, ignore_permissions=True); c.email = "ada@example.com"; c.save(ignore_permissions=True)
    yield customer
    velora.shutdown()


def test_messages_received_and_email_preference(notify_site):
    customer = notify_site
    ps.invite("buyer@example.com", "Bola", "Customer", customer.name)
    me = _login_user("buyer@example.com")
    new_doc("Party Important Date", party_type="Customer", party=customer.name, date_type="Birthday", occasion_date=date(1985, T.month, T.day)).insert(ignore_permissions=True)
    st = eng.settings(); st.send_automatically = 1; st.save(ignore_permissions=True)
    assert eng.run().get("Queued") == 1
    msgs = ps.portal_messages(me, {})["items"]
    assert len(msgs) == 1 and msgs[0]["kind"] == "Birthday" and "birthday" in msgs[0]["subject"].lower()
    assert ps.portal_preferences(me, {})["messages_enabled"] is True
    off = ps.portal_preferences_save(me, {"messages_enabled": False})
    assert off["messages_enabled"] is False and set(off["addresses"]) == {"ada@example.com", "buyer@example.com"}
    assert get_list("Communication Opt-Out", fields=["address"], ignore_permissions=True)
    on = ps.portal_preferences_save(me, {"messages_enabled": True})
    assert on["messages_enabled"] is True and not get_list("Communication Opt-Out", fields=["address"], ignore_permissions=True)
    with pytest.raises(Exception, match="Choose"):
        ps.portal_preferences_save(me, {"messages_enabled": "yes"})
