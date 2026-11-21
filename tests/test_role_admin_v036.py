from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from velora.exceptions import PermissionDenied, ValidationError
from velora.controlplane.role_admin import RoleAdministration

ADMIN = SimpleNamespace(is_company_admin=True, email='admin@company.test', roles={'System Manager'})
USER = SimpleNamespace(is_company_admin=False, email='user@company.test', roles={'Accounts User'})


def service():
    return RoleAdministration(create_engine('sqlite://'))


def test_role_crud_permissions_and_field_restrictions_are_company_local():
    svc = service()
    svc.create_role(ADMIN, 'Accounts Clerk', 'Post invoices and receipts')
    assert svc.set_permission(ADMIN, 'Accounts Clerk', 'Sales Invoice', 'read') == {
        'role': 'Accounts Clerk', 'doctype': 'Sales Invoice', 'permission': 'read', 'allowed': True}
    svc.set_permission(ADMIN, 'Accounts Clerk', 'Sales Invoice', 'submit', False)
    svc.set_field_access(ADMIN, 'Accounts Clerk', 'Customer', 'tax_id', 'hidden')
    result = svc.effective_permissions(ADMIN, 'Accounts Clerk')
    assert {'doctype':'Sales Invoice','permission':'read','allowed':True} in result['permissions']
    assert {'doctype':'Sales Invoice','permission':'submit','allowed':False} in result['permissions']
    assert {'doctype':'Customer','fieldname':'tax_id','access':'hidden'} in result['fields']


def test_role_inheritance_cycle_rejected_and_deny_overrides_allow():
    svc = service()
    svc.create_role(ADMIN, 'Finance Base')
    svc.create_role(ADMIN, 'Finance Manager')
    svc.set_permission(ADMIN, 'Finance Base', 'Payment Entry', 'read', True)
    svc.set_permission(ADMIN, 'Finance Manager', 'Payment Entry', 'read', False)
    svc.set_inheritance(ADMIN, 'Finance Manager', ['Finance Base'])
    effective = svc.effective_permissions(ADMIN, 'Finance Manager')
    assert effective['permissions'] == [{'doctype':'Payment Entry','permission':'read','allowed':False}]
    with pytest.raises(ValidationError):
        svc.set_inheritance(ADMIN, 'Finance Base', ['Finance Manager'])


def test_admin_boundary_and_invalid_permission_are_enforced():
    svc = service()
    with pytest.raises(PermissionDenied): svc.create_role(USER, 'Unauthorized Role')
    svc.create_role(ADMIN, 'Operations User')
    with pytest.raises(ValidationError): svc.set_permission(ADMIN, 'Operations User', 'Sales Invoice', 'approve')
    with pytest.raises(ValidationError): svc.set_field_access(ADMIN, 'Operations User', 'Employee', 'salary', 'visible')


def test_system_role_cannot_be_deactivated():
    svc = service()
    svc.create_role(ADMIN, 'System Operator')
    # Mark as system through the company-local metadata table to exercise the guard.
    from velora.db.system import role_definition
    from sqlalchemy import update
    with svc.engine.begin() as c:
        c.execute(update(role_definition).where(role_definition.c.name == 'System Operator').values(is_system=True))
    with pytest.raises(ValidationError): svc.set_role_active(ADMIN, 'System Operator', False)
