from velora_governance.governance.services.governance_exception_analytics import build_exception_analytics, build_exception_report
from velora_governance.governance.services.governance_sla_integration import normalize_sla_facts


def sample():
    return [
        {"name":"EX-1","status":"Open","severity":"Critical","assigned_to":"","due_date":"2026-10-20","source_doctype":"Board Action"},
        {"name":"EX-2","status":"Escalated","severity":"High","assigned_to":"user1","due_date":"2026-11-22","source_doctype":"Corporate Filing"},
        {"name":"EX-3","status":"Resolved","severity":"Medium","assigned_to":"user2","due_date":"2026-11-26","source_doctype":"Annual Return"},
        {"name":"EX-4","status":"Closed","severity":"Low","assigned_to":"user2","due_date":"2026-11-01","source_doctype":"Board Action"},
    ]


def test_exception_analytics_aging_owner_and_kpis():
    result = build_exception_analytics(sample(), today="2026-11-26")
    assert result["total"] == 4 and result["active"] == 2
    assert result["overdue_active"] == 2 and result["critical_active"] == 1
    assert result["unassigned_active"] == 1 and result["escalated"] == 1
    assert result["aging_buckets"]["30+"] == 1
    assert result["owner_counts"]["user2"] == 2


def test_report_filters_combine_and_summarize():
    result = build_exception_report(sample(), filters={"status":"Open","severity":"Critical"}, today="2026-11-26")
    assert result["count"] == 1 and result["rows"][0]["name"] == "EX-1"
    assert result["analytics"]["critical_active"] == 1


def test_sla_adapter_consumes_external_facts_without_calculating():
    facts = normalize_sla_facts({"sla_provider":"existing_sla_app","sla_status":"Breached","elapsed_seconds":500,"remaining_seconds":-2})
    assert facts["sla_status"] == "Breached" and facts["elapsed_seconds"] == 500
    assert facts["remaining_seconds"] == 0 and facts["integration_state"] == "normalized_external_fact"
    assert normalize_sla_facts({"sla_status":"invented_status"})["sla_status"] == "Unknown"


def test_analytics_accepts_existing_sla_engine_statuses_as_facts():
    result = build_exception_analytics(sample(), today="2026-11-26", sla_records=[
        {"sla_status":"Breached"}, {"sla_status":"On Track"}, {"sla_status":"Met"}
    ])
    assert result["sla"]["breaches_reported_by_sla_engine"] == 1
    assert result["sla"]["integration_state"] == "external_data_consumed"
