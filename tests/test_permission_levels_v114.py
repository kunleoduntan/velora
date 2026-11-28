from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

import velora
from velora.controlplane.role_admin import RoleAdministration
from velora.meta.spec import DocType
from velora.permissions import Session, session_as, field_access

ADMIN = SimpleNamespace(is_company_admin=True, email="admin@company.test", roles={"System Manager"})


def test_docfield_permlevel_is_parsed_and_serialized():
    meta = DocType.from_dict({
        "name": "Sensitive Record",
        "fields": [
            {"fieldname": "title", "fieldtype": "Data"},
            {"fieldname": "margin", "fieldtype": "Currency", "permlevel": 1},
        ],
        "permissions": [
            {"role": "Project User", "read": True, "write": True},
            {"role": "Project Finance", "permlevel": 1, "read": True, "write": True},
        ],
    })
    assert meta.get_field("title").permlevel == 0
    assert meta.get_field("margin").permlevel == 1
    assert meta.get_field("margin").to_dict()["permlevel"] == 1
    assert [(p.role, p.permlevel) for p in meta.permissions] == [("Project User", 0), ("Project Finance", 1)]


def test_permission_grants_are_scoped_by_permlevel(site):
    service = RoleAdministration(velora.db.get_engine())
    service.create_role(ADMIN, "Project User")
    service.set_permission(ADMIN, "Project User", "Sensitive Record", "read", True)
    service.set_permission(ADMIN, "Project User", "Sensitive Record", "write", True)
    service.create_role(ADMIN, "Project Finance")
    service.set_permission(ADMIN, "Project Finance", "Sensitive Record", "read", True, permlevel=1)
    service.set_permission(ADMIN, "Project Finance", "Sensitive Record", "write", False, permlevel=1)

    meta = DocType.from_dict({
        "name": "Sensitive Record",
        "fields": [
            {"fieldname": "title", "fieldtype": "Data"},
            {"fieldname": "margin", "fieldtype": "Currency", "permlevel": 1},
        ],
        "permissions": [],
    })
    with session_as(Session("user@company.test", frozenset({"Project User"}))):
        assert velora.permissions.has_permission(meta, "read", permlevel=0)
        assert velora.permissions.has_permission(meta, "write", permlevel=0)
        assert not velora.permissions.has_permission(meta, "read", permlevel=1)
        assert not velora.permissions.has_permission(meta, "write", permlevel=1)
    with session_as(Session("finance@company.test", frozenset({"Project Finance"}))):
        assert velora.permissions.has_permission(meta, "read", permlevel=1)
        assert not velora.permissions.has_permission(meta, "write", permlevel=1)
        assert not velora.permissions.has_permission(meta, "read", permlevel=0)


def test_field_access_uses_permission_level_not_field_type(site):
    service = RoleAdministration(velora.db.get_engine())
    service.create_role(ADMIN, "Project User")
    service.set_permission(ADMIN, "Project User", "Sensitive Record", "read", True)
    service.set_permission(ADMIN, "Project User", "Sensitive Record", "write", True)
    service.create_role(ADMIN, "Project Finance")
    service.set_permission(ADMIN, "Project Finance", "Sensitive Record", "read", True, permlevel=1)
    service.set_permission(ADMIN, "Project Finance", "Sensitive Record", "write", True, permlevel=1)
    meta = DocType.from_dict({
        "name": "Sensitive Record",
        "fields": [
            {"fieldname": "link_value", "fieldtype": "Link", "options": "Customer", "permlevel": 1},
            {"fieldname": "currency_value", "fieldtype": "Currency", "permlevel": 1},
        ],
        "permissions": [],
    })
    previous = velora.registry._doctypes.get("Sensitive Record")
    velora.registry._doctypes["Sensitive Record"] = meta
    try:
        with session_as(Session("user@company.test", frozenset({"Project User"}))):
            assert field_access("Sensitive Record", "link_value") == "hidden"
            assert field_access("Sensitive Record", "currency_value") == "hidden"
        with session_as(Session("finance@company.test", frozenset({"Project Finance"}))):
            assert field_access("Sensitive Record", "link_value") == "editable"
            assert field_access("Sensitive Record", "currency_value") == "editable"
    finally:
        if previous is None:
            velora.registry._doctypes.pop("Sensitive Record", None)
        else:
            velora.registry._doctypes["Sensitive Record"] = previous
