from datetime import datetime, timezone, timedelta
import pytest
from velora_erp.finance.reporting.audit_evidence import *

def manifest():
 return create_evidence_manifest(report_id="R1",legal_entity="LE1",period={"from_date":"2026-01-01","to_date":"2026-12-31"},snapshot_fingerprint="a"*64,evidence_items=[{"reference":"GL-1","kind":"ledger_extract","sha256":"b"*64}],created_by="preparer")

def test_manifest_and_chain():
 m=manifest(); assert m["complete"]
 log=[]
 for role,action in [("preparer","prepared"),("reviewer","reviewed"),("approver","approved"),("publisher","published")]:
  log=append_audit_event(event_log=log,report_id="R1",actor=role,role=role,action=action,occurred_at="2026-11-15T10:00:00+01:00")
 assert verify_audit_chain(log)["valid"]
 assert validate_report_audit_evidence(manifest=m,event_log=log)["valid"]

def test_chain_detects_tampering():
 log=append_audit_event(event_log=[],report_id="R1",actor="a",role="preparer",action="prepared",occurred_at="2026-11-15T10:00:00Z")
 log[0]["actor"]="intruder"
 assert not verify_audit_chain(log)["valid"]

def test_missing_hash_blocks_manifest():
 m=create_evidence_manifest(report_id="R",legal_entity="L",period={"from_date":"2026-01-01","to_date":"2026-12-31"},snapshot_fingerprint="x",evidence_items=[{"reference":"e1","kind":"support"}],created_by="u")
 assert not m["complete"]

def test_naive_timestamp_rejected():
 with pytest.raises(AuditEvidenceError): append_audit_event(event_log=[],report_id="R",actor="a",role="r",action="prepared",occurred_at="2026-11-15T10:00:00")
