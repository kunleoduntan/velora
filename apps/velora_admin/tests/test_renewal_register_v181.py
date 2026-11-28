from datetime import date
from velora_admin.administration.doctype.renewal_register.renewal_register import renewal_state, renewal_alert_due


def test_renewal_state_expired():
    assert renewal_state("2026-11-20", date(2026, 11, 25)) == {"state": "Expired", "days_remaining": -5}


def test_renewal_state_today():
    assert renewal_state("2026-11-25", date(2026, 11, 25)) == {"state": "Expires Today", "days_remaining": 0}


def test_renewal_state_upcoming():
    assert renewal_state("2026-12-25", date(2026, 11, 25)) == {"state": "Upcoming", "days_remaining": 30}


def test_alert_lead_days_boundary():
    assert renewal_alert_due("2026-12-25", 30, date(2026, 11, 25))
    assert not renewal_alert_due("2026-12-26", 30, date(2026, 11, 25))


def test_overdue_is_always_alert_due():
    assert renewal_alert_due("2026-11-24", 0, date(2026, 11, 25))
