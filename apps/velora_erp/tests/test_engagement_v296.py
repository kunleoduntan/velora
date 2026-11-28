"""Relationship Moments: birthdays, anniversaries, festive occasions, quiet customers, branded email, opt-out and once-only sending."""
from datetime import date, timedelta
import pytest
import velora
from velora import get_doc, get_list, new_doc
from test_cash_transactions import setup_cash
from test_invoice_settlement_v271 import _sales_invoice
from velora_erp.engagement import branding, service as svc

T = date.today()


def _site(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    return accounts, customer, supplier


def _employee(code="E-1", **kw):
    return new_doc("Employee", employee_code=code, first_name=kw.pop("first", "Tunde"), last_name="Bello", employee_type="Permanent", email=kw.pop("email", "tunde@x.com"),
                   date_of_joining=kw.pop("joined", date(2020, 1, 1)), **kw).insert(ignore_permissions=True)


def test_defaults_are_seeded_once_and_are_safe(tmp_path):
    _site(tmp_path)
    try:
        st = svc.settings()
        assert int(st.send_automatically) == 0 and int(st.by_email) == 1          # nothing goes out until a person turns it on
        names = {t["name"] for t in get_list("Moment Template", fields=["name"], limit=100, ignore_permissions=True)}
        assert {"Customer Birthday", "Employee Work Anniversary", "Holiday Greeting", "Customer Win Back"} <= names
        assert {o["name"] for o in get_list("Occasion", fields=["name"], ignore_permissions=True)} >= {"Christmas Day", "New Year's Day"}
        from velora_erp.engagement import defaults
        defaults.ensure()
        assert len(get_list("Moment Template", fields=["name"], limit=100, ignore_permissions=True)) == len(names)
    finally:
        velora.shutdown()


def test_birthday_for_each_kind_of_party_is_held_for_review(tmp_path):
    accounts, customer, supplier = _site(tmp_path)
    try:
        emp = _employee(date_of_birth=date(1990, T.month, T.day) if (T.month, T.day) != (2, 29) else date(1992, 2, 29))
        new_doc("Party Important Date", party_type="Customer", party=customer.name, date_type="Birthday", occasion_date=date(1985, T.month, T.day)).insert(ignore_permissions=True)
        new_doc("Party Important Date", party_type="Supplier", party=supplier.name, date_type="Birthday", occasion_date=date(1970, T.month, T.day)).insert(ignore_permissions=True)
        out = svc.run()
        assert out.get("Held") == 3
        logs = {(r["party_type"], r["kind"]): r for r in get_list("Engagement Log", fields=["party_type", "kind", "status", "subject", "html"], ignore_permissions=True)}
        assert set(logs) == {("Customer", "Birthday"), ("Supplier", "Birthday"), ("Employee", "Birthday")}
        assert "Tunde" in logs[("Employee", "Birthday")]["subject"] and "Acme" in logs[("Customer", "Birthday")]["subject"]
        assert "Happy Birthday" in logs[("Customer", "Birthday")]["html"] and "<table" in logs[("Customer", "Birthday")]["html"]
    finally:
        velora.shutdown()


def test_running_twice_never_repeats_a_moment(tmp_path):
    accounts, customer, supplier = _site(tmp_path)
    try:
        new_doc("Party Important Date", party_type="Customer", party=customer.name, date_type="Birthday", occasion_date=date(1985, T.month, T.day)).insert(ignore_permissions=True)
        assert svc.run().get("Held") == 1
        assert svc.run() == {}
        assert len(get_list("Engagement Log", fields=["name"], ignore_permissions=True)) == 1
    finally:
        velora.shutdown()


def test_work_anniversary_counts_years_and_skips_year_zero(tmp_path):
    _site(tmp_path)
    try:
        _employee("E-5", joined=date(T.year - 5, T.month, T.day) if (T.month, T.day) != (2, 29) else date(T.year - 4, 2, 28))
        _employee("E-0", first="Newbie", email="n@x.com", joined=T)
        kinds = [(m["party"], m["kind"], m.get("years")) for m in svc.moments(T)]
        assert any(k == "Work Anniversary" and y in (4, 5) for _, k, y in kinds)
        assert not any(p.endswith("E-0") or "E-0" in p for p, k, _ in kinds if k == "Work Anniversary")
    finally:
        velora.shutdown()


def test_festive_occasion_reaches_the_chosen_audiences_only(tmp_path):
    accounts, customer, supplier = _site(tmp_path)
    try:
        new_doc("Occasion", occasion_name="Eid", occasion_date=T, repeat_yearly=0, to_customers=1, to_suppliers=0, to_employees=0, enabled=1).insert(ignore_permissions=True)
        _employee()
        svc.run(T)
        rows = get_list("Engagement Log", filters=[["kind", "=", "Holiday"]], fields=["party_type", "subject"], ignore_permissions=True)
        assert {r["party_type"] for r in rows if "Eid" in r["subject"]} == {"Customer"}
        assert any("Eid greetings" in r["subject"] for r in rows)
    finally:
        velora.shutdown()


def test_quiet_customer_gets_one_win_back_and_not_another_soon(tmp_path):
    accounts, customer, supplier = _site(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 500)
        today = inv.invoice_date if hasattr(inv, "invoice_date") else T
        later = T + timedelta(days=200)
        assert [m["kind"] for m in svc.moments(later) if m["kind"] == "Win Back"] == ["Win Back"]
        assert not [m for m in svc.moments(T + timedelta(days=30)) if m["kind"] == "Win Back"]        # not quiet long enough
        assert svc.run(later).get("Held", 0) >= 1
        assert not [m for m in svc.moments(later + timedelta(days=30)) if m["kind"] == "Win Back"]    # nudged recently
        assert [m for m in svc.moments(later + timedelta(days=130)) if m["kind"] == "Win Back"]       # repeat window has passed
        row = get_list("Engagement Log", filters=[["kind", "=", "Win Back"]], fields=["subject", "message"], ignore_permissions=True)[0]
        assert "miss" in row["subject"].lower() and "months" in row["message"]
    finally:
        velora.shutdown()


def test_switches_and_disabled_parties_are_respected(tmp_path):
    accounts, customer, supplier = _site(tmp_path)
    try:
        new_doc("Party Important Date", party_type="Customer", party=customer.name, date_type="Birthday", occasion_date=date(1985, T.month, T.day)).insert(ignore_permissions=True)
        st = svc.settings(); st.birthdays_customers = 0; st.save(ignore_permissions=True)
        assert svc.run() == {}
        st = svc.settings(); st.birthdays_customers = 1; st.save(ignore_permissions=True)
        c = get_doc("Customer", customer.name, ignore_permissions=True); c.disabled = 1; c.save(ignore_permissions=True)
        assert svc.run() == {}
    finally:
        velora.shutdown()


def test_branded_email_is_safe_and_complete():
    html = branding.render_email(brand="Acme <b>Ltd</b>", logo_url="https://x.test/l.png", accent="#123456", emblem="X", heading="Hi <script>", body="Dear A,\n\nSecond <i>para</i>",
                                 button_label="Go", button_url="https://x.test", signature="Regards\nAcme", unsubscribe_url="https://x.test/u?t=1")
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;Ltd" in html and "<i>para" not in html
    assert "#123456" in html and "Unsubscribe" in html and html.count("<p ") >= 3
    assert "javascript:" not in branding.render_email(brand="B", button_label="Go", button_url="javascript:alert(1)")
    assert branding.colour("red") == "#0f6cbd"


def test_template_and_settings_validation(tmp_path):
    _site(tmp_path)
    try:
        with pytest.raises(Exception, match="placeholder"):
            new_doc("Moment Template", template_name="Bad", moment_kind="Custom", audience="All", subject="Hi {{ nope }}", body="x").insert(ignore_permissions=True)
        with pytest.raises(Exception, match="hex colour"):
            st = svc.settings(); st.brand_colour = "blue"; st.save(ignore_permissions=True)
        out = svc.preview("Customer Birthday")
        assert "Ada" in out["subject"] and "Happy Birthday" in out["html"]
    finally:
        velora.shutdown()


def test_app_provider_moments_are_included(tmp_path, monkeypatch):
    accounts, customer, supplier = _site(tmp_path)
    try:
        monkeypatch.setattr(svc, "_providers", lambda on: [{"kind": "Custom", "party_type": "Customer", "party": customer.name, "key": "prov|1", "subject": "Safe travels", "message": "Bon voyage!", "occasion": "Trip"}])
        svc.run()
        row = get_list("Engagement Log", fields=["subject", "message"], ignore_permissions=True)[0]
        assert row["subject"] == "Safe travels" and "Bon voyage" in row["message"]
    finally:
        velora.shutdown()


@pytest.fixture
def notify_site(tmp_path, monkeypatch):
    real = velora.configure
    monkeypatch.setattr(velora, "configure", lambda **kw: real(**{**kw, "apps": kw["apps"] + ["velora_notify"]}))
    accounts, customer, supplier = setup_cash(tmp_path)
    from velora_notify import channels
    channels_settings = {"base_url": "https://erp.test"}
    from velora.settings import set_setting
    set_setting("notify.settings", channels_settings)
    c = get_doc("Customer", customer.name, ignore_permissions=True); c.email = "ada@example.com"; c.save(ignore_permissions=True)
    new_doc("Party Important Date", party_type="Customer", party=customer.name, date_type="Birthday", occasion_date=date(1985, T.month, T.day)).insert(ignore_permissions=True)
    yield customer
    velora.shutdown()


def _deliveries():
    return get_list("Notification Delivery", filters=[["ref_doctype", "=", "Engagement Log"]], fields=["recipient", "channel", "subject", "status", "payload"], ignore_permissions=True)


def test_automatic_sending_queues_a_branded_email_with_an_unsubscribe_link(notify_site):
    st = svc.settings(); st.send_automatically = 1; st.brand_name = "Acme Co"; st.save(ignore_permissions=True)
    assert svc.run().get("Queued") == 1
    d = _deliveries()
    assert len(d) == 1 and d[0]["recipient"] == "ada@example.com" and d[0]["channel"] == "Email" and "birthday" in d[0]["subject"].lower()
    assert "Acme Co" in d[0]["payload"]["html"] and "Unsubscribe" in d[0]["payload"]["html"] and "erp.test/api/public/actions/unsubscribe" in d[0]["payload"]["unsubscribe_url"]
    assert svc.run() == {} and len(_deliveries()) == 1


def test_held_moment_is_sent_only_when_a_person_releases_it(notify_site):
    assert svc.run().get("Held") == 1 and _deliveries() == []
    name = get_list("Engagement Log", fields=["name"], ignore_permissions=True)[0]["name"]
    assert svc.release(name) == "Released"
    assert len(_deliveries()) == 1 and svc.release(name) == "Released" and len(_deliveries()) == 1


def test_opted_out_address_is_never_messaged(notify_site):
    from velora_notify.broadcast.service import record_opt_out
    record_opt_out("ada@example.com", "Email")
    st = svc.settings(); st.send_automatically = 1; st.save(ignore_permissions=True)
    assert svc.run().get("Opted Out") == 1 and _deliveries() == []


def test_missing_address_is_reported_not_guessed(notify_site):
    c = get_doc("Customer", notify_site.name, ignore_permissions=True); c.email = ""; c.save(ignore_permissions=True)
    st = svc.settings(); st.send_automatically = 1; st.save(ignore_permissions=True)
    assert svc.run().get("No Address") == 1 and _deliveries() == []


def test_reports_run_through_the_framework_runner(tmp_path):
    from velora.meta.registry import registry
    from velora.reporting import runner
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        _sales_invoice(accounts, customer, 500)
        new_doc("Party Important Date", party_type="Customer", party=customer.name, date_type="Birthday", occasion_date=date(1985, T.month, T.day)).insert(ignore_permissions=True)
        up = runner.run_definition(registry.report("Upcoming Moments"), {"days": 3})
        assert any(r.values["kind"] == "Birthday" and r.values["party"] == customer.name for r in up.rows)
        quiet = runner.run_definition(registry.report("Quiet Customers and Suppliers"), {"quiet_days": 0})
        assert [r.values["party"] for r in quiet.rows] == [customer.name]
        with pytest.raises(Exception, match="between 1 and 60"):
            runner.run_definition(registry.report("Upcoming Moments"), {"days": 90})
    finally:
        velora.shutdown()
