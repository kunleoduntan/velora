import json, pytest
from decimal import Decimal
from velora_erp.finance.reporting.publication import build_publication_manifest
from velora_erp.finance.reporting.publication_exports import render_publication_excel, _verified_payload
from velora_erp.finance.reporting.disclosure_schedules import build_note_schedule
from velora_erp.finance.reporting.review_workbench import build_review_queue, resolve_review_item, transition_review
from velora_erp.finance.reporting.ias7 import ReportingConfigurationError

def manifest():
    return build_publication_manifest(snapshot={"statement":{"revenue":Decimal("1200.50"),"expense":Decimal("700.25")}},publication_id="PUB-1",legal_entity="ENTITY-1",period_from="2026-01-01",period_to="2026-12-31",prepared_by="preparer",approval_status="Approved")

def test_excel_export_is_from_approved_snapshot():
    data=render_publication_excel(manifest()); assert data[:2]==b"PK"

def test_export_rejects_unapproved_snapshot():
    m=manifest(); m["approval_status"]="Pending"
    with pytest.raises(ReportingConfigurationError): _verified_payload(m)

def test_export_rejects_tampered_snapshot():
    m=manifest(); m["snapshot_json"] += " "
    with pytest.raises(ReportingConfigurationError): _verified_payload(m)

def test_note_schedule_requires_source_refs_and_reconciles_ppe():
    fields={k:Decimal("0") for k in ("opening_cost","additions","disposals","transfers","closing_cost","opening_accumulated_depreciation","depreciation","impairment","disposals_accumulated_depreciation","closing_accumulated_depreciation","closing_carrying_amount")}
    fields["additions"]=Decimal("100"); fields["closing_cost"]=Decimal("100"); fields["closing_carrying_amount"]=Decimal("100")   # cost must reconcile: 0 + 100 additions = 100
    fields.update({k:Decimal("0") for k in ("opening_accumulated_impairment","impairment_reversals","disposals_accumulated_impairment","closing_accumulated_impairment")})   # IAS 36 impairment columns became mandatory in the PPE schedule
    refs={k:"GL:"+k for k in fields}
    result=build_note_schedule(note_code="PPE",current=fields,comparative=fields,source_references=refs,prepared_by="user")
    assert result["complete"]

def test_note_schedule_blocks_missing_sources():
    result=build_note_schedule(note_code="INVENTORY",current={},comparative={},source_references={},prepared_by="user")
    assert not result["complete"] and result["publication_blockers"]

def test_workbench_preparer_may_approve_when_no_workflow_says_otherwise():
    wb=build_review_queue(reporting_pack={"publication_blockers":[]},preparer="alice")
    wb=transition_review(workbench=wb,target_status="In Review",actor="alice",role="Preparer")
    assert transition_review(workbench=wb,target_status="Approved",actor="alice",role="Finance Manager",note="Reviewed")["status"]=="Approved"

def test_workbench_exception_must_be_resolved_before_approval():
    wb=build_review_queue(reporting_pack={"publication_blockers":["Missing cash mapping"]},preparer="alice")
    wb=transition_review(workbench=wb,target_status="In Review",actor="alice",role="Preparer")
    with pytest.raises(ReportingConfigurationError): transition_review(workbench=wb,target_status="Approved",actor="bob",role="Finance Manager",note="Reviewed")
    wb=resolve_review_item(workbench=wb,item_id="EXC-0001",actor="bob",resolution="Mapping approved in source record")
    wb=transition_review(workbench=wb,target_status="Approved",actor="bob",role="Finance Manager",note="Reviewed and reconciled")
    assert wb["status"]=="Approved"

def test_pdf_export_from_approved_snapshot():
    pytest.importorskip("reportlab")
    from velora_erp.finance.reporting.publication_exports import render_publication_pdf
    data=render_publication_pdf(manifest())
    assert data.startswith(b"%PDF")
