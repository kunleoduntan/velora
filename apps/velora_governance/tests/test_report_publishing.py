from velora_governance.governance.services.report_publishing import (
    assemble_board_report_html, build_executive_summary, publication_digest,
    validate_publication_payload,
)


def test_board_report_has_cover_toc_sections_and_appendices():
    report = {"report_title":"Annual ESG Report", "governance_entity":"ENTITY-1",
              "reporting_period":"FY2026", "report_status":"Finalized", "frameworks":["IFRS S1", "IFRS S2"]}
    sections = [{"sequence":2,"section_title":"Strategy","content":"Climate resilience"},
                {"sequence":1,"section_title":"Governance","content":"Oversight"}]
    html = assemble_board_report_html(report=report, sections=sections,
        targets=[{"target":"Net Zero","baseline":2020,"target_value":2030,"current_value":2026,"progress_percent":45,"status":"In Progress"}],
        emissions=[{"scope":"Scope 1","category":"Fuel","activity":"Combustion","quantity":10,"unit":"tonne","tco2e":24}],
        materiality=[{"topic":"Climate","impact_score":5,"financial_score":4,"materiality":"High","priority":"High"}],
        disclosures=[{"framework":"IFRS S2","disclosure_code":"S2-1","disclosure":"Governance","status":"Ready","readiness_percent":100}],
        evidence_references=[{"reference":"EV-1","description":"Board minutes","source":"Secretariat","date":"2026-01-01"}],
        include_draft_watermark=False)
    assert "Annual ESG Report" in html and "Contents" in html
    assert html.index("Governance") < html.index("Strategy")
    for appendix in ("Targets and Performance", "GHG Emissions", "Materiality Assessment", "Framework Disclosure Appendix", "Evidence References"):
        assert appendix in html
    assert "DRAFT — NOT FOR DISTRIBUTION" not in html


def test_report_content_is_escaped():
    report = {"report_title":"<script>alert(1)</script>", "report_status":"Draft"}
    html = assemble_board_report_html(report=report, sections=[{"section_title":"<img src=x>","content":"<script>bad</script>"}])
    assert "&lt;script&gt;" in html
    assert "<script>bad</script>" not in html
    assert "&lt;img" in html


def test_executive_summary_does_not_invent_data():
    summary = build_executive_summary(report={"reporting_period":"FY2026"}, summary_metrics={"Readiness":"78%"})
    assert "FY2026" in summary and "78%" in summary
    assert "No highlights provided." in summary


def test_publication_validation_requires_finalized_and_review_checks():
    result = validate_publication_payload({"publication_channel":"Website"},
        report={"report_status":"Draft"}, sections=[{"content":""}], open_issue_count=2, approved_review_count=0)
    assert not result["eligible"]
    assert len(result["blockers"]) >= 4


def test_publication_validation_eligible_when_controls_met():
    result = validate_publication_payload({"publication_channel":"Board Portal","publication_date":"2026-11-26"},
        report={"report_status":"Finalized"}, sections=[{"section_status":"Completed","content":"Done"}],
        open_issue_count=0, approved_review_count=1)
    assert result["eligible"]
    assert result["publication_channel"] == "Board Portal"


def test_publication_digest_is_stable_and_content_sensitive():
    a = publication_digest("report content")
    assert a == publication_digest("report content")
    assert a != publication_digest("changed report")
    assert len(a) == 64
