from datetime import date
import pytest
from velora_projectone.projectone.services.enterprise_capacity import (
    build_enterprise_capacity, build_escalation_register,
)


def fixture_rows():
    profiles = [{"name":"RP-1", "resource_id":"RES-1", "display_name":"Ada",
                 "calendar_id":"CAL-1", "daily_capacity_hours":8,
                 "working_weekdays":"0,1,2,3,4", "active":True}]
    calendars = [{"name":"CAL-1", "working_weekdays":"0,1,2,3,4",
                  "holiday_dates":"[\"2026-11-17\"]", "active":True}]
    tasks = [{"name":"TASK-1", "project":"P-1", "resource_profile":"RP-1",
              "planned_start":"2026-11-16", "planned_finish":"2026-11-20",
              "estimated_hours":40, "status":"In Progress"},
             {"name":"TASK-2", "project":"P-2", "resource_profile":"RP-1",
              "planned_start":"2026-11-16", "planned_finish":"2026-11-20",
              "estimated_hours":20, "status":"Open"}]
    allocations = [{"project":"P-1", "resource":"RES-1", "status":"Open",
                    "approved_by":"PM-1", "planned_hours":40, "start_date":"2026-11-16",
                    "end_date":"2026-11-30", "approval_reference":"APR-1"},
                   {"project":"P-2", "resource":"RES-1", "status":"Draft",
                    "planned_hours":100}]
    exceptions = [{"resource":"RP-1", "exception_date":"2026-11-18",
                   "available_hours":2, "reason":"Training"}]
    return profiles, tasks, allocations, calendars, exceptions


def test_capacity_aggregates_task_demand_across_projects_and_applies_holidays_exceptions():
    p,t,a,c,e=fixture_rows()
    result=build_enterprise_capacity(p,t,a,c,e,start_date="2026-11-16",end_date="2026-11-20")
    assert len(result["resources"]) == 1
    resource=result["resources"][0]
    # 60 effort hours across four working days (Tuesday is a holiday), 15h/day.
    assert resource["demand_hours"] == 60
    assert resource["overallocated_days"] == 4
    wed=next(x for x in result["daily_capacity"] if x["date"]=="2026-11-18")
    assert wed["capacity_hours"] == 2
    assert wed["demand_hours"] == 15
    assert len(result["approved_allocations"]) == 1
    assert result["metadata"]["resource_reservations_created"] is False


def test_resource_calendar_weekdays_and_active_dates_limit_capacity():
    p,t,a,c,e=fixture_rows()
    p[0]["working_weekdays"]="0,1,2,3,4,5"
    p[0]["active_from"]="2026-11-18"
    p[0]["active_to"]="2026-11-20"
    c[0]["holiday_dates"]=""
    result=build_enterprise_capacity(p,[],[],c,[],start_date="2026-11-16",end_date="2026-11-21")
    dates={x["date"]:x["capacity_hours"] for x in result["daily_capacity"]}
    assert "2026-11-16" not in dates
    assert dates["2026-11-18"] == 8
    assert "2026-11-21" not in dates  # non-working Saturday has no capacity row


def test_capacity_rejects_duplicate_exceptions_and_oversized_period():
    p,t,a,c,e=fixture_rows()
    e.append(dict(e[0]))
    with pytest.raises(ValueError,match="Duplicate availability exception"):
        build_enterprise_capacity(p,t,a,c,e,start_date="2026-11-16",end_date="2026-11-20")
    with pytest.raises(ValueError,match="no longer than 366 days"):
        build_enterprise_capacity(p,t,a,c,[],start_date="2026-01-01",end_date="2027-01-03")


def test_missing_task_dates_are_reported_not_silently_assigned():
    p,t,a,c,e=fixture_rows()
    t.append({"name":"TASK-X","resource_profile":"RP-1","estimated_hours":8,"status":"Open"})
    result=build_enterprise_capacity(p,t,a,c,e,start_date="2026-11-16",end_date="2026-11-20")
    assert {x["task"] for x in result["excluded_tasks"]} == {"TASK-X"}


def test_escalation_register_reports_overdue_due_soon_and_blocked_without_sending():
    tasks=[{"name":"T1","project":"P1","title":"Late","status":"In Progress","planned_finish":"2026-11-20","assignee":"U1"},
           {"name":"T2","project":"P1","title":"Due","status":"Open","planned_finish":"2026-11-23"},
           {"name":"T3","project":"P1","title":"Held","status":"On Hold","planned_finish":"2026-12-20"}]
    result=build_escalation_register(tasks,as_of="2026-11-21",due_soon_days=3)
    assert [x["escalation"] for x in result["items"]] == ["Overdue","Blocked","Due Soon"]
    assert result["delivery"] == "not_sent_host_notification_adapter_required"
    assert result["items"][0]["notification_intent"]["requires_host_notification_adapter"] is True


def test_duplicate_display_name_alias_is_not_guessed():
    p,t,a,c,e=fixture_rows()
    p.append({"name":"RP-2","resource_id":"RES-2","display_name":"Ada",
              "daily_capacity_hours":8,"working_weekdays":"0,1,2,3,4","active":True})
    t[0].pop("resource_profile")
    t[0]["assignee"]="Ada"
    result=build_enterprise_capacity(p,t,a,c,e,start_date="2026-11-16",end_date="2026-11-20")
    assert all(row["resource_id"] != "RES-2" or row["demand_hours"] == 0 for row in result["resources"])
    assert result["resources"][0]["demand_hours"] == 20  # TASK-2 remains explicitly linked to RES-1


def test_missing_or_inactive_resource_calendar_is_rejected():
    p,t,a,c,e=fixture_rows()
    c[0]["active"] = False
    with pytest.raises(ValueError,match="missing or inactive calendar"):
        build_enterprise_capacity(p,t,a,c,e,start_date="2026-11-16",end_date="2026-11-20")
