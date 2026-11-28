from datetime import date, datetime, timedelta
from types import SimpleNamespace
import pytest
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from test_cash_transactions import setup_cash
from velora_erp.support import api as support_api, desk, jobs, service as svc, sla as S


def cal(**kw):
    base = dict(round_the_clock=False, start=S.time(8, 0), end=S.time(17, 0), days=frozenset({0, 1, 2, 3, 4}), holidays=frozenset(), utc_offset=0.0)
    base.update(kw)
    return S.Calendar(**base)


FRI16 = datetime(2026, 11, 20, 16, 0)       # a Friday


def test_working_hours_arithmetic():
    c = cal()
    assert S.add_working_seconds(c, FRI16, 2 * 3600) == datetime(2026, 11, 23, 9, 0)                      # an hour left on Friday, one on Monday
    assert S.add_working_seconds(c, datetime(2026, 11, 21, 10, 0), 3600) == datetime(2026, 11, 23, 9, 0)  # Saturday start waits for Monday
    assert S.add_working_seconds(c, FRI16, 3600) == datetime(2026, 11, 20, 17, 0)
    assert S.add_working_seconds(cal(holidays=frozenset({date(2026, 11, 23)})), FRI16, 2 * 3600) == datetime(2026, 11, 24, 9, 0)
    assert S.working_seconds_between(c, FRI16, datetime(2026, 11, 23, 9, 0)) == 2 * 3600
    assert S.working_seconds_between(c, datetime(2026, 11, 21, 9, 0), datetime(2026, 11, 22, 9, 0)) == 0
    # a team one hour ahead of UTC: 06:30 UTC is 07:30 local, before the 08:00 start
    assert S.add_working_seconds(cal(utc_offset=1.0), datetime(2026, 11, 23, 6, 30), 3600) == datetime(2026, 11, 23, 8, 0)
    r = cal(round_the_clock=True)
    assert S.add_working_seconds(r, FRI16, 10 * 3600) == datetime(2026, 11, 21, 2, 0)


def test_state_thresholds():
    c = cal(round_the_clock=True)
    start = datetime(2026, 11, 18, 8, 0)
    due = start + timedelta(hours=10)
    assert S.state(c, start, due, start + timedelta(hours=5), 80) == "On track"
    assert S.state(c, start, due, start + timedelta(hours=8), 80) == "At risk"
    assert S.state(c, start, due, due, 80) == "Breached"


def test_pause_pushes_deadlines():
    c = cal(round_the_clock=True)
    t = SimpleNamespace(sla=None, first_response_due=datetime(2026, 11, 18, 12), first_responded_on=None, resolution_due=datetime(2026, 11, 19, 12), resolved_on=None)
    svc.calendar_for = lambda sla: c                                   # no agreement needed for the arithmetic
    svc.shift_for_pause(t, datetime(2026, 11, 18, 9), datetime(2026, 11, 18, 11))
    assert t.first_response_due == datetime(2026, 11, 18, 14) and t.resolution_due == datetime(2026, 11, 19, 14)


@pytest.fixture
def desk_site(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    new_doc("Support Settings", settings_name="Default").insert(ignore_permissions=True)
    cat = new_doc("Support Category", category_name="Billing").insert(ignore_permissions=True)
    team = new_doc("Support Team", team_name="Front Line", team_lead="lead@x.com", assignment="Round robin",
                   members=[{"user": "a@x.com", "active": 1}, {"user": "b@x.com", "active": 1}]).insert(ignore_permissions=True)
    default = new_doc("Service Level Agreement", sla_name="Standard", is_default=1, utc_offset_hours=0, escalate_to="boss@x.com",
                      targets=[{"priority": p, "first_response_hours": fr, "resolution_hours": rs} for p, fr, rs in (("Low", 8, 72), ("Medium", 4, 24), ("High", 2, 8), ("Urgent", 1, 4))]).insert(ignore_permissions=True)
    return SimpleNamespace(customer=customer, cat=cat, team=team, default=default)


def ticket(s, **kw):
    vals = dict(subject="Cannot log in", customer=s.customer.name, team=s.team.name, priority="Medium")
    vals.update(kw)
    return new_doc("Support Ticket", **vals).insert(ignore_permissions=True)


def test_new_ticket_gets_clock_and_round_robin_agent(desk_site):
    t1, t2, t3 = ticket(desk_site), ticket(desk_site), ticket(desk_site)
    assert t1.sla == "Standard" and t1.first_response_due and t1.resolution_due > t1.first_response_due
    assert [t.assigned_to for t in (t1, t2, t3)] == ["a@x.com", "b@x.com", "a@x.com"]
    assert t1.response_sla in ("On track", "At risk") and t1.status == "Open"


def test_most_specific_agreement_wins(desk_site):
    s = desk_site
    new_doc("Service Level Agreement", sla_name="Billing only", category=s.cat.name, utc_offset_hours=0,
            targets=[{"priority": "Medium", "first_response_hours": 1, "resolution_hours": 2}]).insert(ignore_permissions=True)
    assert ticket(s, category=s.cat.name).sla == "Billing only"
    new_doc("Service Level Agreement", sla_name="Gold customer", customer=s.customer.name, utc_offset_hours=0,
            targets=[{"priority": "Medium", "first_response_hours": 1, "resolution_hours": 2}]).insert(ignore_permissions=True)
    assert ticket(s, category=s.cat.name).sla == "Gold customer"


def test_agreement_validation(desk_site):
    bad = lambda **kw: new_doc("Service Level Agreement", sla_name=kw.pop("n"), utc_offset_hours=0, **kw).insert(ignore_permissions=True)
    with pytest.raises(ValidationError):
        bad(n="a", targets=[{"priority": "Low", "first_response_hours": 5, "resolution_hours": 2}])
    with pytest.raises(ValidationError):
        bad(n="b", targets=[{"priority": "Low", "first_response_hours": 1, "resolution_hours": 2}, {"priority": "Low", "first_response_hours": 1, "resolution_hours": 2}])
    with pytest.raises(ValidationError):
        bad(n="c", is_default=1, targets=[{"priority": "Low", "first_response_hours": 1, "resolution_hours": 2}])     # a second default
    with pytest.raises(ValidationError):
        bad(n="d", work_start="17:00", work_end="08:00", targets=[{"priority": "Low", "first_response_hours": 1, "resolution_hours": 2}])


def test_reply_meets_response_and_watcher_breaches_and_escalates(desk_site):
    s = desk_site
    quiet, late = ticket(s), ticket(s, subject="Printer down")
    support_api.reply(quiet.name, "We are looking into it.")
    quiet = get_doc("Support Ticket", quiet.name)
    assert quiet.first_responded_on and quiet.response_sla == "Met" and quiet.status == "In Progress"
    far = late.first_response_due + timedelta(minutes=1)
    stats = jobs.check_sla(now=far)
    late = get_doc("Support Ticket", late.name)
    assert late.response_sla == "Breached" and late.escalation_level == 1 and late.assigned_to == "boss@x.com"
    assert stats["breached"] >= 1
    again = jobs.check_sla(now=far + timedelta(minutes=1))
    assert get_doc("Support Ticket", late.name).escalation_level == 1 and again["escalated"] == 0       # one escalation per breach, not one per minute


def test_waiting_on_customer_pauses_then_resolution_and_reopen(desk_site):
    t = ticket(desk_site)
    t.status = "Waiting on Customer"
    t.save(ignore_permissions=True)
    assert t.response_sla == "Paused" and t.paused_since
    assert jobs.check_sla(now=t.resolution_due + timedelta(days=3))["breached"] == 0            # a paused clock cannot breach
    t.status = "In Progress"
    t.save(ignore_permissions=True)
    assert t.paused_since is None
    t.status = "Resolved"
    with pytest.raises(ValidationError):
        t.save(ignore_permissions=True)                                                          # a resolution note is required
    t.resolution_notes = "Password reset."
    t.save(ignore_permissions=True)
    assert t.resolved_on and t.resolution_sla == "Met"
    assert jobs.auto_close(now=t.resolved_on + timedelta(days=8)) == 1
    t = get_doc("Support Ticket", t.name)
    assert t.status == "Closed" and t.closed_on
    t.status = "In Progress"
    with pytest.raises(ValidationError):
        t.save(ignore_permissions=True)                                                          # closed tickets are only reopened
    t.status = "Open"
    t.save(ignore_permissions=True)
    assert t.reopen_count == 1 and t.resolved_on is None


def test_customer_reply_reopens_and_desk_numbers(desk_site):
    s = desk_site
    a, b = ticket(s), ticket(s, priority="Urgent", subject="Site down")
    a.status = "Waiting on Customer"
    a.save(ignore_permissions=True)
    support_api.reply(a.name, "It still fails.", kind="Customer reply")
    assert get_doc("Support Ticket", a.name).status == "Open"
    d = desk.summary("a@x.com")
    k = d["kpis"]
    assert k["open"] == 2 and k["unassigned"] == 0 and d["queue"][0]["name"] in (a.name, b.name)
    assert len(d["trend"]) == 14 and d["workload"]
    with pytest.raises(ValidationError):
        support_api.reply(a.name, "  ")


def test_portal_complaint_opens_a_ticket_with_a_clock(desk_site):
    import test_portal_v281 as tp
    from velora_erp import portal_service as ps
    ps.invite("buyer@example.com", "Bola", "Customer", desk_site.customer.name)
    buyer = tp._login_user("buyer@example.com")
    made = ps.customer_complaint_create(buyer, {"category": "Service", "description": "Nobody called back", "severity": "Critical"})
    ticket = get_doc("Support Ticket", made["ticket"])
    assert ticket.priority == "Urgent" and ticket.source == "Portal" and ticket.sla == "Standard" and ticket.reference_name == made["name"]
    assert ps.customer_complaints(buyer, {})["items"][0]["ticket"] == ticket.name
