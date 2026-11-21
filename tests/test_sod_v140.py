from types import SimpleNamespace
import pytest
from sqlalchemy import select

from velora import db
from velora.controlplane.role_admin import RoleAdministration
from velora.db.system import role_conflict
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import Session, _assert_no_role_conflicts, _effective_roles, session_as

ADMIN = SimpleNamespace(is_company_admin=True, email="admin@velora.test", roles={"System Manager"})


def test_role_conflict_is_unordered_and_requires_active_roles(site):
    service = RoleAdministration(db.get_engine())
    service.create_role(ADMIN, "Payment Maker")
    service.create_role(ADMIN, "Payment Approver")
    assert service.set_role_conflict(ADMIN, "Payment Approver", "Payment Maker", "Maker cannot approve") == {
        "role_a": "Payment Approver", "role_b": "Payment Maker", "reason": "Maker cannot approve"}
    assert service.list_role_conflicts(ADMIN)[0]["reason"] == "Maker cannot approve"
    with pytest.raises(ValidationError, match="cannot conflict with itself"):
        service.set_role_conflict(ADMIN, "Payment Maker", "Payment Maker")
    assert service.clear_role_conflict(ADMIN, "Payment Maker", "Payment Approver")["deleted"] == 1


def test_conflicting_effective_roles_are_denied_at_authorization_boundary(site):
    service = RoleAdministration(db.get_engine())
    service.create_role(ADMIN, "Cash Clerk")
    service.create_role(ADMIN, "Cash Approver")
    service.set_role_conflict(ADMIN, "Cash Clerk", "Cash Approver", "Cash duties must be separated")
    with pytest.raises(PermissionDenied, match="segregation of duties"):
        with session_as(Session("clerk@velora.test", frozenset({"Cash Clerk", "Cash Approver"}))):
            _assert_no_role_conflicts(_effective_roles(Session("clerk@velora.test", frozenset({"Cash Clerk", "Cash Approver"}))))


def test_role_conflict_applies_through_inherited_roles(site):
    service = RoleAdministration(db.get_engine())
    for role in ("Cash Maker", "Cash Reviewer", "Senior Finance"):
        service.create_role(ADMIN, role)
    service.set_inheritance(ADMIN, "Senior Finance", ["Cash Reviewer"])
    service.set_role_conflict(ADMIN, "Cash Maker", "Cash Reviewer")
    session = Session("finance@velora.test", frozenset({"Cash Maker", "Senior Finance"}))
    with pytest.raises(PermissionDenied, match="Conflicting roles"):
        _assert_no_role_conflicts(_effective_roles(session))
