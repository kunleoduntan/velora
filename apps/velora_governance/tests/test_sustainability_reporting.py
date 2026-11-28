from velora_governance.governance.services.sustainability_reporting import readiness, status_for_readiness, assess_disclosures, generate_content_blocks

def test_readiness_average_components():
    assert readiness(required_data_points=2,complete_data_points=1,evidence_required=True,evidence_complete=False,narrative_required=True,narrative_complete=True)==50.0

def test_status():
    assert status_for_readiness(100)=="Ready"
    assert status_for_readiness(0)=="Not Started"
    assert status_for_readiness(50)=="In Progress"
    assert status_for_readiness(100,applicable=False)=="Not Applicable"

def test_assessment_gaps():
    rows=assess_disclosures([{"disclosure":"D1","applicable":True,"data_points_required":2,"evidence_required":True,"narrative_required":True}],{"D1":1},{"D1":False},{"D1":False})
    assert rows[0]["assessment_status"]=="In Progress"
    assert "Data points missing" in rows[0]["gap_summary"] and "Evidence required" in rows[0]["gap_summary"]

def test_content_blocks():
    blocks=generate_content_blocks(entity_name="Demo Co",period_name="FY2026",framework_name="IFRS S1",disclosures=[{"disclosure":"D1","disclosure_title":"Governance"}],metrics=[{"Energy":"100 MWh"}])
    assert len(blocks)==3 and blocks[0]["block_type"]=="Executive Summary"

from velora_governance.governance.services.sustainability_reporting import create_collection_task_specs, map_records_to_disclosures, assemble_report_package

def test_collection_tasks_are_idempotent_and_skip_not_applicable():
    requirements = [
        {"disclosure": "D1", "applicable": True, "required_data_points": 2, "evidence_required": True, "narrative_required": True},
        {"disclosure": "D2", "applicable": False, "required_data_points": 1, "evidence_required": True},
    ]
    tasks = create_collection_task_specs(reporting_period="FY26", disclosure_requirements=requirements)
    assert len(tasks) == 3
    existing = {tasks[0]["task_key"]}
    rerun = create_collection_task_specs(reporting_period="FY26", disclosure_requirements=requirements, existing_task_keys=existing)
    assert len(rerun) == 2
    assert all("D2" not in t["task_key"] for t in tasks)

def test_record_mapping_and_report_package():
    disclosures = [{"disclosure": "D1", "applicable": True, "data_points_required": 2, "evidence_required": True, "narrative_required": True}]
    dps = [{"name": "DP-1", "disclosure": "D1", "status": "Verified"}, {"name": "DP-2", "disclosure": "D1", "status": "Draft"}]
    evidence = [{"name": "EV-1", "disclosure": "D1", "status": "Submitted"}]
    mapped = map_records_to_disclosures(disclosure_rows=disclosures, datapoints=dps, evidence=evidence, narratives={"D1": "Draft narrative"})
    assert mapped[0]["complete_data_points"] == 1 and mapped[0]["evidence_complete"]
    package = assemble_report_package(entity_name="Demo", period_name="FY26", frameworks=["IFRS S1"], disclosure_rows=disclosures, datapoints=dps, evidence=evidence, narratives={"D1": "Draft narrative"})
    assert package["summary"]["readiness_percent"] == 83.33
    assert package["report_status"] == "In Progress"
    assert package["content_blocks"]

def test_framework_field_statuses_are_respected():
    from velora_governance.governance.services.sustainability_reporting import map_records_to_disclosures
    mapped = map_records_to_disclosures(
        disclosure_rows=[{"disclosure": "D1", "applicable": True, "data_points_required": 1, "evidence_required": True}],
        datapoints=[{"name": "DP1", "disclosure": "D1", "verification_status": "Verified"}],
        evidence=[{"name": "EV1", "disclosure": "D1", "verified": False}],
    )
    assert mapped[0]["complete_data_points"] == 1
    assert mapped[0]["evidence_complete"] is False


def test_disclosure_requirements_are_configuration_driven():
    from velora_governance.governance.services.sustainability_reporting import build_disclosure_data_requirements
    reqs = build_disclosure_data_requirements([
        {"name": "D1", "applicable": True, "data_points_required": 3, "evidence_required": True, "narrative_required": False},
        {"name": "D2", "applicable": False, "data_points_required": 5, "evidence_required": True},
    ])
    assert reqs[0]["required_data_points"] == 3
    assert reqs[0]["evidence_required"] is True
    assert reqs[0]["narrative_required"] is False
    assert reqs[1]["applicable"] is False
