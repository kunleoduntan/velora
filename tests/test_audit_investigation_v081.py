import pytest
import velora
from velora import activity
from velora.permissions import Session, session_as
from velora.exceptions import PermissionDenied

def test_audit_feed_filters_and_csv_export(site):
    with session_as(Session("auditor",frozenset({"System Manager"}))):
        activity.record_event("admin","Policy configuration changed",summary="Rule adjusted",source="ui")
        activity.record_event("approval","Invoice approved",doctype="Sales Invoice",document_name="SINV-1",summary="Approved")
        r=activity.feed(limit=50,event_type="approval",doctype="Sales Invoice")
        assert r["total"]==1 and r["items"][0]["title"]=="Invoice approved"
        csv=activity.export_feed(event_type="approval")
        assert csv["exported"]==1 and "Invoice approved" in csv["content"]

def test_audit_case_lifecycle_and_immutable_notes(site):
    with session_as(Session("compliance.user",frozenset({"Auditor"}))):
        created=activity.create_case("Unusual journal entry","Investigate unusual posting","High")
        assert created["status"]=="Open"
        updated=activity.update_case(created["id"],status="In Review",note="Obtained supporting schedule")
        assert updated["case"]["status"]=="In Review"
        assert len(updated["notes"])==2
        assert updated["notes"][-1]["body"]=="Obtained supporting schedule"
        activity.update_case(created["id"],status="Closed")
        assert activity.get_case(created["id"])["case"]["status"]=="Closed"

def test_audit_case_management_requires_audit_role(site):
    with session_as(Session("ordinary.user",frozenset({"Sales User"}))):
        with pytest.raises(PermissionDenied): activity.list_cases()
        with pytest.raises(PermissionDenied): activity.create_case("Not permitted")
