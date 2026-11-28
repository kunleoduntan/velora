import pytest
from velora_projectone.projectone.services.performance import calculate_earned_value
from velora_projectone.projectone.services.risk import score_risk
from velora_projectone.projectone.services.financial import calculate_budget_position
from velora_projectone.projectone.services.scheduling import calculate_schedule

def test_earned_value_metrics():
    r=calculate_earned_value(100,80,90,200)
    assert r["sv"] == -20 and r["cv"] == -10
    assert str(r["spi"]) == "0.8" and r["cpi"] < 1
    assert r["eac"] == 225

def test_earned_value_zero_denominator_is_null():
    r=calculate_earned_value(0,0,0)
    assert r["spi"] is None and r["cpi"] is None

def test_risk_score_validation_and_band():
    assert score_risk(5,5)["severity"] == "Critical"
    with pytest.raises(ValueError): score_risk(6,2)

def test_budget_excludes_pending_changes():
    r=calculate_budget_position(100,20,30,15)
    assert r["available_budget"] == 50
    assert r["pending_change_excluded"] == 15

def test_cpm_forward_backward_pass():
    r=calculate_schedule([{"id":"A","duration":3},{"id":"B","duration":4,"predecessors":["A"]},{"id":"C","duration":2,"predecessors":["A"]},{"id":"D","duration":1,"predecessors":["B","C"]}])
    assert r["duration"] == 8
    assert r["critical_activities"] == ["A","B","D"]

def test_cpm_cycle_rejected():
    with pytest.raises(ValueError): calculate_schedule([{"id":"A","duration":1,"predecessors":["B"]},{"id":"B","duration":1,"predecessors":["A"]}])


def test_cpm_supports_relationship_types_and_lag():
    r = calculate_schedule([
        {"id": "A", "duration": 4},
        {"id": "B", "duration": 3, "dependencies": [{"predecessor": "A", "type": "SS", "lag": 1}]},
        {"id": "C", "duration": 2, "dependencies": [{"predecessor": "A", "type": "FF", "lag": 0}]},
    ])
    assert r["relationship_support"] == ["FF", "SS"]
    assert next(x for x in r["activities"] if x["id"] == "B")["early_start"] == 1


def test_project_lifecycle_requires_evidence():
    from velora_projectone.projectone.services.lifecycle import transition_project, validate_project
    validate_project({"title":"ERP rollout", "project_code":"ERP-01", "project_manager":"pm@example.com", "progress_percent":0})
    with pytest.raises(ValueError): transition_project("Planning", "Active", {})
    assert transition_project("Planning", "Active", {"approved_baseline": True})["to_status"] == "Active"


def test_project_closure_requires_reconciliation_and_handover():
    from velora_projectone.projectone.services.lifecycle import transition_project
    with pytest.raises(ValueError): transition_project("Completed", "Closed", {"financial_reconciled": True})
    evidence = {"financial_reconciled": True, "commitments_cleared": True, "handover_accepted": True, "closure_approved": True}
    assert transition_project("Completed", "Closed", evidence)["requires_audit_event"]


def test_approved_baseline_is_immutable():
    from velora_projectone.projectone.services.lifecycle import validate_baseline_mutation
    with pytest.raises(ValueError): validate_baseline_mutation("Approved")
    assert validate_baseline_mutation("Draft")


def test_project_row_scope_and_financial_redaction():
    from velora_projectone.projectone.security.policy import ProjectPrincipal, assert_project_access, redact_financial_fields
    principal = ProjectPrincipal("u1", frozenset({"C1"}), {"P1":"Project Manager"})
    assert assert_project_access(principal, "P1", "C1", {"Project Manager"})
    with pytest.raises(PermissionError): assert_project_access(principal, "P2", "C1")
    visible = redact_financial_fields({"name":"P1", "approved_budget":100}, False)
    assert visible == {"name":"P1"}
    protected = redact_financial_fields({"name":"P1", "current_period_profit":50,
        "cumulative_revenue":200,"cost_performance_index":0.8,"status":"Approved"}, False)
    assert protected == {"name":"P1", "status":"Approved"}


def test_working_calendar_skips_weekends_and_holidays():
    from velora_projectone.projectone.services.calendar import add_working_days, working_days_between
    holidays = ["2026-12-25"]
    assert add_working_days("2026-12-24", 1, holidays=holidays) == "2026-12-28"
    assert working_days_between("2026-12-24", "2026-12-28", holidays=holidays) == 2


def test_resource_capacity_aggregates_and_flags_overallocation():
    from velora_projectone.projectone.services.resources import evaluate_resource_capacity
    r = evaluate_resource_capacity({("EMP-1", "2026-W48"): 40}, [
        {"resource_id":"EMP-1", "period":"2026-W48", "hours":25},
        {"resource_id":"EMP-1", "period":"2026-W48", "hours":20},
    ])
    assert r["overallocated_count"] == 1
    assert r["resources"][0]["available_hours"] == -5


def test_labour_cost_is_decimal_safe():
    from velora_projectone.projectone.services.resources import calculate_labour_cost
    assert calculate_labour_cost("2.5", "1200")["labour_cost"] == 3000


def test_commitment_reconciliation_reduces_invoiced_and_cancelled_values():
    from velora_projectone.projectone.services.project_finance import reconcile_commitment
    r = reconcile_commitment("1000", "350", "150")
    assert r["open_commitment"] == 500
    with pytest.raises(ValueError): reconcile_commitment(100, 90, 20)


def test_project_financial_position_keeps_revenue_separate_from_cost():
    from velora_projectone.projectone.services.project_finance import calculate_project_financial_position
    r = calculate_project_financial_position(1000, 400, 100, 900, 800)
    assert r["available_budget"] == 500
    assert r["forecast_project_margin"] == 100


def test_source_reference_explicitly_disallows_projectone_ledger_write():
    from velora_projectone.projectone.services.project_finance import validate_source_reference
    r = validate_source_reference("Purchase Invoice", "PINV-1", "PRJ-1", 250, "NGN")
    assert r["ledger_write_permitted"] is False
    assert r["posting_authority"] == "source_application"


def test_portfolio_summary_aggregates_permission_filtered_rows():
    from velora_projectone.projectone.reports.portfolio_summary import build_portfolio_summary
    r = build_portfolio_summary([
        {"status":"Active", "approved_budget":100, "actual_cost":30, "open_commitments":20},
        {"status":"Completed", "approved_budget":50, "actual_cost":40, "open_commitments":0},
    ])
    assert r["project_count"] == 2 and r["available_budget"] == 60

def test_project_repository_optimistic_concurrency_and_immutable_code():
    from velora_projectone.projectone.services.projects import InMemoryProjectRepository, create_project, update_project
    repo=InMemoryProjectRepository()
    row=create_project(repo,{"title":"ERP Rollout","project_code":"ERP-26","project_manager":"pm@x.test"})
    updated=update_project(repo,row["name"],{"title":"ERP Transformation"},1)
    assert updated["version"]==2 and updated["title"]=="ERP Transformation"
    with pytest.raises(RuntimeError): update_project(repo,row["name"],{"title":"Stale"},1)
    with pytest.raises(ValueError): update_project(repo,row["name"],{"project_code":"X"},2)

def test_dated_schedule_respects_weekends_and_finish_start():
    from velora_projectone.projectone.services.schedule_dates import calculate_dated_schedule
    r=calculate_dated_schedule([{"id":"A","duration":2},{"id":"B","duration":1,"dependencies":[{"predecessor":"A","type":"FS"}]}],"2026-11-20")
    rows={x["id"]:x for x in r["activities"]}
    assert rows["A"]["early_finish"]=="2026-11-23"
    assert rows["B"]["early_start"]=="2026-11-24"

def test_resource_leveling_exposes_unassigned_hours():
    from velora_projectone.projectone.services.resource_planning import level_allocations, match_resource_skills
    r=level_allocations([{"id":"A","resource_id":"E1","period":"W1","hours":6,"priority":1},{"id":"B","resource_id":"E1","period":"W1","hours":5,"priority":2}],{("E1","W1"):8})
    assert r["unassigned_hours"]==3
    assert r["allocations"][1]["assigned_hours"]==2
    m=match_resource_skills([{"activity_id":"T1","skills":["Python"]}],[{"resource_id":"E1","skills":["Python"]}])
    assert m[0]["candidates"][0]["resource_id"]=="E1"

def test_cost_forecast_excludes_pending_change_from_revised_budget():
    from velora_projectone.projectone.services.commercial import cost_forecast, billing_position
    r=cost_forecast(1000,400,100,600,approved_changes=50,pending_changes=200)
    assert r["revised_budget"]==1050 and r["estimate_at_completion"]==1100 and r["pending_changes_excluded"]==200
    b=billing_position(1000,100,500,450,5)
    assert b["unbilled_contract_value"]==600 and b["retention_amount"]==25

def test_agile_metrics_only_count_accepted_done_stories():
    from velora_projectone.projectone.services.agile import sprint_metrics
    r=sprint_metrics([{"story_points":5,"status":"Done","accepted":True},{"story_points":3,"status":"Done","accepted":False},{"story_points":2,"status":"Blocked"}])
    assert r["accepted_points"]==5 and r["unaccepted_done_points"]==3 and r["blocked_story_count"]==1

def test_risk_change_and_quality_controls():
    from velora_projectone.projectone.services.controls import assess_risk, validate_change_request, quality_gate
    assert assess_risk({"probability":5,"impact":4,"owner":"pm"})["requires_escalation"]
    with pytest.raises(ValueError): validate_change_request({"change_id":"CR1","project_id":"P1","description":"scope","requested_by":"u","impact_assessment":"high","status":"Approved"})
    assert quality_gate({"deliverable_id":"D1","acceptance_criteria":"AC","inspector":"u","inspection_date":"2026-11-21","result":"Accepted"})["completion_allowed"]

def test_executive_dashboard_and_ai_assist_are_read_only():
    from velora_projectone.projectone.reports.executive import executive_dashboard
    from velora_projectone.projectone.services.ai_assist import project_insights
    r=executive_dashboard([{"status":"Active","approved_budget":100,"actual_cost":60,"open_commitments":20,"critical_risks":1}])
    assert r["available_budget"]==20 and r["critical_risks"]==1
    a=project_insights({"name":"P1","status":"Active","approved_baseline":False})
    assert a["advisory_only"] and a["records_changed"] is False

def test_timesheet_requires_approval_reference_for_payroll_handoff():
    from velora_projectone.projectone.services.timesheets import validate_timesheet, aggregate_timesheet_hours
    base={"employee":"E1","project":"P1","work_date":"2026-11-20","hours":"7.5","status":"Approved","approved_by":"M1","approval_reference":"APR-1"}
    assert validate_timesheet(base)["payroll_handoff_permitted"]
    bad=dict(base); bad.pop("approval_reference")
    with pytest.raises(ValueError): validate_timesheet(bad)
    assert aggregate_timesheet_hours([base])[0]["approved_hours"]==7.5

def test_project_authorization_requires_role_and_company_membership():
    from velora_projectone.projectone.security.policy import ProjectPrincipal
    from velora_projectone.projectone.security.authorization import authorize_project_action
    principal=ProjectPrincipal("u1",frozenset({"C1"}),{"P1":"Project Manager"})
    assert authorize_project_action(principal,"edit_plan","P1","C1")
    with pytest.raises(PermissionError): authorize_project_action(principal,"approve_budget","P1","C1")
    with pytest.raises(PermissionError): authorize_project_action(principal,"view","P1","C2")


# v1.4.0 advanced schedule, Gantt projection and baseline controls

def test_advanced_cpm_calculates_total_and_free_float():
    from velora_projectone.projectone.services.advanced_schedule import calculate_cpm
    result = calculate_cpm([
        {"id":"A", "duration":3},
        {"id":"B", "duration":4, "dependencies":[{"predecessor":"A", "type":"FS"}]},
        {"id":"C", "duration":2, "dependencies":[{"predecessor":"A", "type":"FS"}]},
        {"id":"D", "duration":1, "dependencies":[{"predecessor":"B", "type":"FS"}, {"predecessor":"C", "type":"FS"}]},
    ])
    rows = {x["id"]: x for x in result["activities"]}
    assert result["duration"] == 8
    assert rows["C"]["total_float"] == 2
    assert rows["A"]["free_float"] == 0
    assert rows["B"]["critical"] is True


def test_advanced_cpm_supports_all_relationship_types_and_negative_lag():
    from velora_projectone.projectone.services.advanced_schedule import calculate_cpm
    result = calculate_cpm([
        {"id":"A", "duration":5},
        {"id":"B", "duration":2, "dependencies":[{"predecessor":"A", "type":"SS", "lag":1}]},
        {"id":"C", "duration":2, "dependencies":[{"predecessor":"A", "type":"FF", "lag":-1}]},
        {"id":"D", "duration":1, "dependencies":[{"predecessor":"A", "type":"SF", "lag":0}]},
    ])
    assert result["duration"] == 5
    assert {p["type"] for x in result["activities"] for p in x["predecessors"]} == {"SS", "FF", "SF"}


def test_gantt_projection_uses_working_calendar_and_milestones():
    from velora_projectone.projectone.services.advanced_schedule import calculate_gantt
    result = calculate_gantt([
        {"id":"A", "name":"Design", "duration":2},
        {"id":"M", "name":"Approval", "duration":0, "dependencies":[{"predecessor":"A", "type":"FS"}]},
        {"id":"B", "name":"Build", "duration":2, "dependencies":[{"predecessor":"M", "type":"FS"}]},
    ], "2026-11-20")
    rows = {x["id"]: x for x in result["gantt_rows"]}
    assert rows["A"]["early_start_date"] == "2026-11-20"
    assert rows["A"]["early_finish_date"] == "2026-11-23"
    assert rows["M"]["milestone"] is True
    assert rows["M"]["early_start_date"] == "2026-11-24"
    assert rows["B"]["early_start_date"] == "2026-11-24"


def test_baseline_comparison_reports_added_removed_and_schedule_variance():
    from velora_projectone.projectone.services.advanced_schedule import compare_schedule_to_baseline
    result = compare_schedule_to_baseline(
        [{"id":"A", "start_date":"2026-11-03", "finish_date":"2026-11-08"},
         {"id":"C", "start_date":"2026-11-01", "finish_date":"2026-11-02"}],
        [{"id":"A", "start_date":"2026-11-01", "finish_date":"2026-11-05"},
         {"id":"B", "start_date":"2026-11-02", "finish_date":"2026-11-04"}])
    rows = {x["id"]: x for x in result["tasks"]}
    assert rows["A"]["finish_variance_days"] == 3
    assert rows["B"]["change"] == "Removed"
    assert rows["C"]["change"] == "Added"
    assert result["delayed_count"] == 1
    assert result["baseline_is_read_only"] is True


def test_advanced_schedule_rejects_dependency_cycles_and_bad_ids():
    from velora_projectone.projectone.services.advanced_schedule import calculate_cpm
    with pytest.raises(ValueError, match="cycle"):
        calculate_cpm([{"id":"A", "duration":1, "predecessors":["B"]},
                       {"id":"B", "duration":1, "predecessors":["A"]}])
    with pytest.raises(ValueError, match="unique"):
        calculate_cpm([{"id":"A", "duration":1}, {"id":"A", "duration":2}])

# v1.5.0 Agile delivery controls

def _ready_story(story_id, points=3, rank=1, **overrides):
    row = {"story_id": story_id, "title": f"Story {story_id}", "story_points": points,
           "acceptance_criteria": "Given a user, when action is taken, then result is correct",
           "assignee": "user@example.test", "priority": "High", "dependencies_assessed": True,
           "status": "Ready", "backlog_rank": rank, "estimated_hours": 4}
    row.update(overrides)
    return row


def test_agile_definition_of_ready_and_done_gates():
    from velora_projectone.projectone.services.agile import validate_story, transition_story
    story = _ready_story("US-1")
    assert validate_story(story, require_ready=True)["definition_of_ready"]
    assert transition_story({**story, "status": "Open"}, "Ready")["status"] == "Ready"
    with pytest.raises(ValueError):
        transition_story({**story, "status": "In Review", "tests_passed": False}, "Done")
    done = {**story, "status": "In Review", "acceptance_criteria_met": True,
            "reviewed": True, "tests_passed": True, "documentation_updated": True}
    assert transition_story(done, "Done")["status"] == "Done"


def test_sprint_planning_respects_story_and_hour_capacity():
    from velora_projectone.projectone.services.agile import plan_sprint
    sprint = {"sprint_id":"SP-1", "start_date":"2026-11-23", "end_date":"2026-12-04", "capacity_points":5}
    result = plan_sprint(sprint, [_ready_story("US-1",3,1), _ready_story("US-2",3,2)], team_capacity_hours=8)
    assert result["selected_story_ids"] == ["US-1"]
    assert result["deferred"][0]["story_id"] == "US-2"
    assert result["remaining_points"] == 2


def test_sprint_planning_rejects_not_ready_story():
    from velora_projectone.projectone.services.agile import plan_sprint
    sprint = {"sprint_id":"SP-1", "start_date":"2026-11-23", "end_date":"2026-12-04", "capacity_points":8}
    with pytest.raises(ValueError, match="Definition of Ready"):
        plan_sprint(sprint, [{"story_id":"US-1", "title":"Incomplete", "status":"Open"}])


def test_kanban_board_reports_wip_limit_and_blocked_cards():
    from velora_projectone.projectone.services.agile import kanban_board
    stories = [_ready_story("US-1", status="In Progress"), _ready_story("US-2", status="Blocked")]
    result = kanban_board(stories, wip_limits={"In Progress":1})
    column = next(c for c in result["columns"] if c["name"] == "In Progress")
    assert column["count"] == 2 and column["wip_exceeded"]
    assert sum(1 for x in column["items"] if x["blocked"]) == 1


def test_burndown_uses_persisted_daily_accepted_completion():
    from velora_projectone.projectone.services.agile import burndown
    result = burndown({"start_date":"2026-11-23", "end_date":"2026-11-25"},
                      [{"story_points":8}], daily_completed={"2026-11-24":3})
    assert result["points"][1]["actual_remaining"] == 5
    assert result["points"][0]["ideal_remaining"] == 8
    assert result["points"][2]["ideal_remaining"] == 0


def test_sprint_review_does_not_count_unaccepted_done_as_delivered():
    from velora_projectone.projectone.services.agile import sprint_review
    result = sprint_review([{"story_id":"US-1","story_points":5,"status":"Done","accepted":True},
                            {"story_id":"US-2","story_points":3,"status":"Done","accepted":False}])
    assert result["metrics"]["accepted_points"] == 5
    assert result["carried_forward_stories"] == ["US-2"]


def test_retrospective_requires_owned_dated_actions():
    from velora_projectone.projectone.services.agile import validate_retrospective
    data = {"sprint_id":"SP-1", "facilitator":"SM-1", "what_went_well":"Pairing",
            "what_to_improve":"Testing earlier", "actions":[{"action":"Add test review", "owner":"U1", "due_date":"2026-12-01"}]}
    assert validate_retrospective(data)["action_count"] == 1
    with pytest.raises(ValueError):
        validate_retrospective({**data, "actions":[{"action":"No owner"}]})


def test_sprint_capacity_validation_and_iso_dates():
    from velora_projectone.projectone.services.agile import validate_sprint
    sprint = {"sprint_id":"SP-1", "start_date":"2026-11-23", "end_date":"2026-12-04", "capacity_points":5}
    assert validate_sprint(sprint, [_ready_story("US-1",4)])['remaining_capacity'] == 1
    with pytest.raises(ValueError, match="exceeds point capacity"):
        validate_sprint(sprint, [_ready_story("US-1",6)])


def test_reopening_accepted_story_clears_acceptance_for_retest():
    from velora_projectone.projectone.services.agile import transition_story
    story = {"story_id":"US-9", "title":"Accepted story", "status":"Done", "accepted":True}
    reopened = transition_story(story, "In Progress")
    assert reopened["accepted"] is False


def test_approved_timesheet_daily_limit_applies_across_projects():
    from velora_projectone.projectone.services.timesheets import aggregate_timesheet_hours
    entries = [
        {"employee":"E1","project":"P1","work_date":"2026-11-20","hours":14,"status":"Approved","approved_by":"M1","approval_reference":"A1"},
        {"employee":"E1","project":"P2","work_date":"2026-11-20","hours":11,"status":"Approved","approved_by":"M1","approval_reference":"A2"},
    ]
    import pytest
    with pytest.raises(ValueError, match="across all projects"):
        aggregate_timesheet_hours(entries)
