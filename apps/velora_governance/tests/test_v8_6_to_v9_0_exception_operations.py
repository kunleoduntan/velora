from velora_governance.governance.services.governance_exception_persistence import (
    exception_key, normalize_exception_payload, transition_persisted_exception
)


def test_exception_key_deterministic_and_source_scoped():
    a = exception_key("Board Action", "BA-1", "Overdue")
    assert a == exception_key("Board Action", "BA-1", "Overdue")
    assert a != exception_key("Board Action", "BA-2", "Overdue")


def test_normalization_rejects_unknown_source():
    result = normalize_exception_payload({"source_doctype":"User", "source_name":"x", "title":"test"})
    assert not result["valid"]


def test_normalization_classifies_and_resolves_route():
    result = normalize_exception_payload({"source_doctype":"Board Action", "source_name":"BA-1",
        "exception_type":"Overdue", "title":"Action overdue", "due_date":"2020-01-01"},
        routing_config={"Critical":"Governance Administrator"})
    assert result["valid"]
    assert result["normalized"]["severity"] == "Critical"
    assert result["normalized"]["routing_status"] == "Configured"


def test_transition_persisted_requires_evidence():
    class Doc:
        status="In Progress"; name="GE-1"; resolution_evidence=""; resolved_by=None; resolved_on=None; closed_by=None; closed_on=None
        def save(self, **kwargs): self.saved=True
    doc=Doc()
    try:
        transition_persisted_exception(doc,"Resolved",actor="user@example.com",evidence=None,evidence_required=True)
    except ValueError as e:
        assert str(e)=="resolution_evidence_required"
    else:
        raise AssertionError("evidence should be required")
    result=transition_persisted_exception(doc,"Resolved",actor="user@example.com",evidence="Approved minutes",evidence_required=True,now="2026-11-26")
    assert result["status"]=="Resolved" and doc.saved and doc.resolution_evidence
