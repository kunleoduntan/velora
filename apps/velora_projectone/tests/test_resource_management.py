from decimal import Decimal
import pytest
from velora_projectone.projectone.services.resource_management import (
    validate_resource_profile, match_resource_skills, build_resource_capacity,
    validate_allocation, evaluate_utilisation, level_resource_assignments,
    validate_timesheet, transition_timesheet, approved_hours_handoff,
)


def profile(rid="R-1", **kw):
    return {"resource_id":rid,"resource_type":"Employee","display_name":rid,
            "daily_capacity_hours":8,"active":True,**kw}


def test_profile_validation_and_bounds():
    assert validate_resource_profile(profile())["daily_capacity_hours"] == 8
    with pytest.raises(ValueError): validate_resource_profile(profile(daily_capacity_hours=25))
    with pytest.raises(ValueError): validate_resource_profile({"resource_id":"x"})


def test_skill_matching_ranks_proficiency_and_skips_inactive():
    req=[{"activity_id":"A","skills":["Python","SQL"],"minimum_proficiency":2}]
    resources=[{"resource_id":"low","skills":["Python","SQL"],"skill_levels":{"Python":2,"SQL":2}},
               {"resource_id":"expert","skills":["Python","SQL"],"skill_levels":{"Python":5,"SQL":4}},
               {"resource_id":"off","skills":["Python","SQL"],"active":False}]
    result=match_resource_skills(req,resources)[0]["candidates"]
    assert [x["resource_id"] for x in result] == ["expert","low"]


def test_capacity_honours_weekends_holidays_and_exceptions():
    result=build_resource_capacity([profile()],start_date="2026-11-23",end_date="2026-11-27",
        allocations=[{"resource_id":"R-1","start_date":"2026-11-23","end_date":"2026-11-27","hours_per_day":6}],
        exceptions=[{"resource_id":"R-1","date":"2026-11-25","available_hours":4}],holidays=["2026-11-26"])
    days={x["date"]:x for x in result["days"]}
    assert len(days)==4
    assert days["2026-11-25"]["overallocated"] is True
    assert days["2026-11-24"]["available_hours"]==2


def test_capacity_rejects_unknown_resource_and_bad_dates():
    with pytest.raises(ValueError): build_resource_capacity([profile()],start_date="2026-11-23",end_date="2026-11-24",allocations=[{"resource_id":"bad","start_date":"2026-11-23","end_date":"2026-11-24","hours_per_day":2}])
    with pytest.raises(ValueError): build_resource_capacity([profile()],start_date="bad",end_date="2026-11-24")


def test_allocation_validates_and_capacity_limits():
    a={"allocation_id":"AL-1","project":"P-1","resource_id":"R-1","start_date":"2026-11-23","end_date":"2026-11-24","hours_per_day":9}
    assert validate_allocation(a)["valid"]
    with pytest.raises(ValueError): validate_allocation({**a,"allocation_percent":101})
    with pytest.raises(ValueError): validate_allocation({**a,"end_date":"2026-11-20"})


def test_utilisation_flags_high_and_overallocation():
    result=evaluate_utilisation([{"resource_id":"R1","capacity_hours":10,"allocated_hours":9},{"resource_id":"R2","capacity_hours":8,"allocated_hours":9}])
    assert result["high_utilisation_resources"]==2
    assert result["overallocated_resources"]==1


def test_leveling_preserves_shortage_instead_of_hiding_it():
    assignments=[{"allocation_id":"A1","project":"P1","resource_id":"R1","start_date":"2026-11-23","end_date":"2026-11-23","hours_per_day":6}]
    result=level_resource_assignments(assignments,{("R1","2026-11-23"):4})
    assert result["total_unassigned_hours"]==2
    assert result["allocations"][0]["fully_levelled"] is False


def valid_ts(**kw):
    return {"timesheet_id":"TS-1","employee":"EMP-1","project":"PRJ-1","work_date":"2026-11-23","hours":7.5,"submitted_by":"user-a","status":"Draft",**kw}


def test_timesheet_validation_and_payroll_boundary():
    result=validate_timesheet(valid_ts())
    assert result["ledger_write_permitted"] is False
    assert result["payroll_handoff_permitted"] is False
    with pytest.raises(ValueError): validate_timesheet(valid_ts(hours=24.1))


def test_timesheet_submit_then_approve_requires_separation():
    submitted=transition_timesheet(valid_ts(),"Submitted",actor_id="user-a")
    assert submitted["status"]=="Submitted"
    with pytest.raises(ValueError): transition_timesheet(submitted,"Approved",actor_id="user-a",approval_reference="APR-1")
    approved=transition_timesheet(submitted,"Approved",actor_id="manager",approval_reference="APR-1")
    assert validate_timesheet(approved)["payroll_handoff_permitted"] is True


def test_timesheet_approved_is_immutable_and_invalid_transition_rejected():
    approved={**valid_ts(status="Approved",approved_by="manager",approval_reference="APR" )}
    with pytest.raises(ValueError): transition_timesheet(approved,"Rejected",actor_id="manager")
    with pytest.raises(ValueError): transition_timesheet(valid_ts(),"Approved",actor_id="manager",approval_reference="APR")


def test_approved_hours_handoff_only_approved_and_unique():
    approved={**valid_ts(status="Approved",approved_by="manager",approval_reference="APR-1")}
    pending=valid_ts(timesheet_id="TS-2",status="Submitted")
    payload=approved_hours_handoff([approved,pending],company_id="COMP-1",handoff_batch_id="BATCH-1")
    assert payload["entry_count"]==1
    assert payload["payroll_calculation_performed"] is False
    assert payload["gl_posting_performed"] is False


def test_handoff_rejects_duplicate_timesheet_ids_and_missing_scope():
    approved={**valid_ts(status="Approved",approved_by="manager",approval_reference="APR-1")}
    with pytest.raises(ValueError): approved_hours_handoff([approved,approved],company_id="C",handoff_batch_id="B")
    with pytest.raises(ValueError): approved_hours_handoff([approved],company_id="",handoff_batch_id="B")


def test_weekly_timesheet_expands_only_approved_daily_lines():
    from velora_projectone.projectone.services.resource_management import expand_approved_timesheets
    sheets=[{"name":"WTS-1","employee":"E1","project":"P1","approval_status":"Approved",
             "submitted_by":"staff","approved_by":"manager","approval_reference":"APR-1",
             "entries":[{"name":"LINE-1","work_date":"2026-11-23","hours":7.5,"project":"P1"}]},
            {"name":"WTS-2","employee":"E1","project":"P1","approval_status":"Pending Approval","entries":[{"work_date":"2026-11-24","hours":8}]}]
    rows=expand_approved_timesheets(sheets)
    assert len(rows)==1 and rows[0]["timesheet_id"]=="WTS-1:LINE-1"
    assert validate_timesheet(rows[0])["payroll_handoff_permitted"] is True


def test_timesheet_pending_approval_status_maps_to_submitted():
    row=valid_ts(approval_status="Pending Approval")
    row.pop("status")
    assert validate_timesheet(row)["status"]=="Submitted"
    changed=transition_timesheet(row,"Approved",actor_id="manager",approval_reference="APR")
    assert changed["approval_status"]=="Approved"


def test_handoff_enforces_employee_daily_total_across_projects():
    a={**valid_ts(timesheet_id="TS-A",project="P-A",hours=14,status="Approved",approved_by="mgr",approval_reference="A")}
    b={**valid_ts(timesheet_id="TS-B",project="P-B",hours=11,status="Approved",approved_by="mgr",approval_reference="B")}
    with pytest.raises(ValueError,match="exceed 24"):
        approved_hours_handoff([a,b],company_id="C1",handoff_batch_id="B1")


def test_resource_api_routes_are_registered_without_untrusted_timesheet_commands():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, operation: operation())
    paths = {route.path for route in app.routes}
    expected = {
        "/api/projectone/resources/profile/validate",
        "/api/projectone/resources/skills/rank",
        "/api/projectone/resources/capacity/calendar",
        "/api/projectone/resources/allocation/validate",
        "/api/projectone/resources/utilisation",
        "/api/projectone/resources/level-calendar",
    }
    assert expected.issubset(paths)
    assert "/api/projectone/timesheets/transition" not in paths
    assert "/api/projectone/timesheets/handoff" not in paths
    assert "/api/projectone/timesheets/approved-hours" not in paths


def test_timesheet_validation_accepts_native_doctype_name_as_id():
    row=valid_ts()
    row["name"]=row.pop("timesheet_id")
    result=validate_timesheet(row)
    assert result["timesheet_id"]=="TS-1"
