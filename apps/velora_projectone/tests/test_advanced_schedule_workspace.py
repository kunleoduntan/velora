import pytest
from velora_projectone.projectone.services.advanced_schedule import (
    calculate_cpm, calculate_gantt, preview_schedule_change,
)

ACTIVITIES = [
    {"id": "A", "name": "Design", "duration": 3, "dependencies": []},
    {"id": "B", "name": "Build", "duration": 5,
     "dependencies": [{"predecessor": "A", "type": "FS", "lag": 0}]},
    {"id": "C", "name": "Test", "duration": 2,
     "dependencies": [{"predecessor": "B", "type": "FS", "lag": 0}]},
]


def test_cpm_respects_planned_start_constraint_and_propagates_downstream():
    result = calculate_cpm([{**ACTIVITIES[0], "planned_start_offset": 4}, *ACTIVITIES[1:]])
    rows = {row["id"]: row for row in result["activities"]}
    assert rows["A"]["early_start"] == 4
    assert rows["B"]["early_start"] == 7
    assert rows["C"]["early_start"] == 12


def test_schedule_preview_is_read_only_and_reports_downstream_impact():
    result = preview_schedule_change(ACTIVITIES, "2026-12-01", "A", 4)
    assert result["preview_only"] is True
    assert result["persisted"] is False
    assert result["baseline_modified"] is False
    assert result["resource_reservations_created"] is False
    assert result["approval_required_before_commit"] is True
    assert result["previous_project_finish"] == "2026-12-14"
    assert result["proposed_project_finish"] == "2026-12-18"
    assert {row["task_id"] for row in result["impacts"]} == {"A", "B", "C"}


def test_schedule_preview_rejects_unknown_task_and_negative_offset():
    with pytest.raises(ValueError):
        preview_schedule_change(ACTIVITIES, "2026-12-01", "MISSING", 2)
    with pytest.raises(ValueError):
        preview_schedule_change(ACTIVITIES, "2026-12-01", "A", -1)


def test_schedule_preview_optional_baseline_comparison_is_read_only():
    baseline = [
        {"id": "A", "start_date": "2026-12-01", "finish_date": "2026-12-03"},
        {"id": "B", "start_date": "2026-12-04", "finish_date": "2026-12-10"},
        {"id": "C", "start_date": "2026-12-11", "finish_date": "2026-12-14"},
    ]
    result = preview_schedule_change(ACTIVITIES, "2026-12-01", "A", 4, baseline=baseline)
    assert result["baseline_comparison"]["changed_count"] == 3
    assert result["baseline_comparison"]["baseline_is_read_only"] is True


def test_gantt_keeps_milestone_zero_duration():
    result = calculate_gantt([{"id": "M", "duration": 0}], "2026-12-01")
    assert result["gantt_rows"][0]["early_start_date"] == result["gantt_rows"][0]["early_finish_date"]
