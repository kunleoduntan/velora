from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace as NS
import pytest

from velora_erp.hr.recruitment_services import build_recruitment_dashboard, validate_interview_slot, build_recruitment_notification
from velora_erp.naming_series import validate_pattern, render_pattern, series_scope


def test_recruitment_dashboard_uses_configured_pipeline():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    result = build_recruitment_dashboard(
        applications=[{"application_stage": "Applied"}, {"application_stage": "Interview"}],
        vacancies=[{"status": "Open"}, {"status": "Closed"}],
        interviews=[{"scheduled_start": now + timedelta(hours=2), "interview_status": "Scheduled"}],
        offers=[{"offer_status": "Accepted"}], pipeline_stages=["Applied", "Interview", "Offer"], now=now)
    assert result["application_count"] == 2
    assert result["open_vacancy_count"] == 1
    assert [x["count"] for x in result["pipeline"]] == [1, 1, 0]
    assert result["upcoming_interviews"] == 1
    assert result["offers_accepted"] == 1


def test_interview_panel_overlap_is_rejected():
    start = datetime(2026, 11, 18, 10, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="conflict"):
        validate_interview_slot(start=start, end=start + timedelta(hours=1), interviewer_ids=["u1"],
            existing_interviews=[{"name":"INT-1", "scheduled_start":start + timedelta(minutes=30),
                "scheduled_end":start + timedelta(hours=2), "panel_member_ids":["u1"], "interview_status":"Scheduled"}])


def test_interview_panel_allows_non_overlapping_slot():
    start = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    validate_interview_slot(start=start, end=start + timedelta(hours=1), interviewer_ids=["u1"],
        existing_interviews=[{"name":"INT-1", "scheduled_start":start - timedelta(hours=2),
            "scheduled_end":start - timedelta(hours=1), "panel_member_ids":["u1"], "interview_status":"Scheduled"}])


def test_notification_requires_complete_routing_data():
    with pytest.raises(ValueError): build_recruitment_notification(recipient="", subject="s", message="m", event_type="e")
    item=build_recruitment_notification(recipient="hr@example.test",subject="Interview",message="Due",event_type="interview_due")
    assert item["notification_status"] == "Unread"


def test_naming_pattern_render_is_configurable():
    pattern="{company}-{doctype}-{YYYY}{MM}-{SEQ:5}"
    assert render_pattern(pattern,company="CMP",doctype="Invoice",posting_date=date(2026,11,17),sequence=23)=="CMP-Invoice-202611-00023"
    assert series_scope(company="CMP",doctype="Invoice",fiscal_period="FY26") == "CMP|Invoice|FY26"


def test_naming_pattern_requires_exactly_one_sequence():
    with pytest.raises(ValueError): validate_pattern("INV-{YYYY}{MM}")
    with pytest.raises(ValueError): validate_pattern("INV-{SEQ}-{SEQ}")
