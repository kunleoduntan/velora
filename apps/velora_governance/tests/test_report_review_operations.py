from velora_governance.governance.services.report_review_operations import (
    review_queue, validate_review_payload, validate_issue_payload,
    report_completeness, assemble_report_html, next_revision_number,
)


def test_review_queue_filters_and_counts():
    rows = [
        {"report":"R1","reviewer":"a","review_status":"Pending","review_round":1},
        {"report":"R1","reviewer":"b","review_status":"Returned for Changes","review_round":1},
        {"report":"R2","reviewer":"a","review_status":"Completed","review_round":2},
    ]
    q = review_queue(rows, reviewer="a")
    assert q["total"] == 2 and q["pending"] == 1 and q["completed"] == 1


def test_review_payload_validation_defaults():
    v = validate_review_payload({"report":"R1","reviewer":"user","review_role":"Finance"})
    assert v["review_round"] == 1 and v["review_status"] == "Pending"


def test_review_payload_rejects_missing_reviewer():
    try: validate_review_payload({"report":"R1","review_role":"Finance"})
    except ValueError as e: assert "Reviewer" in str(e)
    else: assert False


def test_issue_payload_defaults_and_validation():
    v = validate_issue_payload({"report":"R1","issue_title":"Missing emissions data"})
    assert v["severity"] == "Medium" and v["issue_status"] == "Open"


def test_issue_payload_rejects_bad_severity():
    try: validate_issue_payload({"report":"R1","issue_title":"x","severity":"Urgent"})
    except ValueError: pass
    else: assert False


def test_completeness_excludes_not_applicable_and_counts_open_issues():
    result = report_completeness({"report_status":"Approved"}, [
        {"section_status":"Completed"}, {"section_status":"Not Applicable"}, {"section_status":"Not Started"}
    ], [{"issue_status":"Open"},{"issue_status":"Resolved"}])
    assert result["sections_applicable"] == 2
    assert result["section_completeness_percent"] == 50
    assert result["open_review_issues"] == 1
    assert not result["report_ready_for_finalization"]


def test_report_ready_only_when_approved_complete_and_issue_free():
    result = report_completeness({"report_status":"Approved"}, [{"section_status":"Completed"}], [])
    assert result["report_ready_for_finalization"] is True


def test_html_assembly_escapes_user_content_and_includes_sections():
    html = assemble_report_html(report={"report_title":"<unsafe>","report_status":"Draft"}, sections=[
        {"section_title":"Climate","content":"<script>alert(1)</script> & narrative"}
    ])
    assert "&lt;unsafe&gt;" in html
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "Climate" in html


def test_revision_number_increments():
    assert next_revision_number([{"revision_number":1},{"revision_number":4}]) == 5


def test_finalization_guard_returns_actionable_blockers():
    from velora_governance.governance.services.report_review_operations import validate_finalization
    result = validate_finalization({"report_status":"In Review"}, [{"section_status":"Not Started"}], [{"issue_status":"Open"}], approved_review_count=0)
    assert result["eligible"] is False
    assert len(result["blockers"]) == 4


def test_finalization_guard_passes_approved_complete_issue_free_report():
    from velora_governance.governance.services.report_review_operations import validate_finalization
    result = validate_finalization({"report_status":"Approved"}, [{"section_status":"Completed"}], [], approved_review_count=1)
    assert result["eligible"] is True and result["blockers"] == []
