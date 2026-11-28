import pytest

from velora import signatures
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from test_workflow_hardening import S, customer, define, act, start, ADMIN  # noqa: F401


def test_signature_is_added_on_approval_only_when_signing_is_on(site, monkeypatch):
    signatures.set_signature("boss@company.test", "  K.  Oduntan ")
    assert signatures.get_signature("boss@company.test") == "K. Oduntan"
    with pytest.raises(ValidationError):
        signatures.set_signature("boss@company.test", "x" * 41)
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "final": True}])
    c = customer()
    monkeypatch.setattr(signatures, "signing_enabled", lambda dt=None: False)
    iid = start("WF", "Customer", c.name)["id"]
    with session_as(S("boss@company.test", "Approver")):
        act(iid, "Approve")
    assert signatures.trail("Customer", c.name) == []
    monkeypatch.setattr(signatures, "signing_enabled", lambda dt=None: True)
    c2 = customer()
    iid2 = start("WF", "Customer", c2.name)["id"]
    with session_as(S("boss@company.test", "Approver")):
        act(iid2, "Approve")
    t = signatures.trail("Customer", c2.name)
    assert len(t) == 1 and t[0]["signature"] == "K. Oduntan" and t[0]["action"] == "Approve" and t[0]["signed_on"][2] == "/"
