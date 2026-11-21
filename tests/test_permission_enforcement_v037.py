from types import SimpleNamespace
import pytest
import velora
from sqlalchemy import create_engine
from velora.controlplane.role_admin import RoleAdministration
from velora.permissions import session_as
from velora.exceptions import PermissionDenied

ADMIN = SimpleNamespace(is_company_admin=True, email='admin@acme.test', roles={'System Manager'})


def setup_policy(site, allow_write=False):
    svc = RoleAdministration(velora.db.get_engine())
    svc.create_role(ADMIN, 'RBAC Clerk')
    svc.set_permission(ADMIN, 'RBAC Clerk', 'Customer', 'create', True)
    svc.set_permission(ADMIN, 'RBAC Clerk', 'Customer', 'read', True)
    svc.set_permission(ADMIN, 'RBAC Clerk', 'Customer', 'write', allow_write)
    svc.set_field_access(ADMIN, 'RBAC Clerk', 'Customer', 'email', 'hidden')
    svc.set_field_access(ADMIN, 'RBAC Clerk', 'Customer', 'credit_limit', 'read_only')
    return svc


def test_rbac_deny_overrides_metadata_and_inheritance(site):
    svc = setup_policy(site)
    svc.create_role(ADMIN, 'Regional Clerk')
    svc.set_inheritance(ADMIN, 'Regional Clerk', ['RBAC Clerk'])
    with session_as(velora.Session('clerk@acme.test', frozenset({'Regional Clerk'}))):
        meta = velora.registry.get('Customer')
        assert velora.permissions.has_permission(meta, 'read')
        assert not velora.permissions.has_permission(meta, 'write')
        created = velora.new_doc('Customer', customer_name='Allowed Customer').insert()
        with pytest.raises(PermissionDenied):
            created.email = 'blocked@example.test'
            created.save()


def test_field_read_and_write_enforcement(site):
    setup_policy(site, allow_write=True)
    with session_as(velora.Session('clerk@acme.test', frozenset({'RBAC Clerk'}))):
        doc = velora.new_doc('Customer', customer_name='Visible Customer')
        doc.insert()
        payload = doc.as_dict()
        assert 'email' not in payload
        with pytest.raises(PermissionDenied, match='credit_limit'):
            doc.credit_limit = 100
            doc.save()
        with pytest.raises(PermissionDenied, match='not readable'):
            velora.get_list('Customer', fields=['name', 'email'])


def test_policy_is_company_database_local(site):
    setup_policy(site)
    # A role without configured policies continues to use its DocType metadata grants.
    with session_as(velora.Session('other@acme.test', frozenset({'Sales User'}))):
        meta = velora.registry.get('Customer')
        assert velora.permissions.has_permission(meta, 'read') in (True, False)


def test_hidden_field_cannot_be_used_as_filter_and_inactive_role_is_ignored(site):
    svc = setup_policy(site)
    with session_as(velora.Session('clerk@acme.test', frozenset({'RBAC Clerk'}))):
        with pytest.raises(PermissionDenied, match='hidden'):
            velora.get_list('Customer', filters={'email': 'secret@example.test'})
    svc.set_role_active(ADMIN, 'RBAC Clerk', False)
    with session_as(velora.Session('clerk@acme.test', frozenset({'RBAC Clerk'}))):
        meta = velora.registry.get('Customer')
        # An inactive catalog role cannot retain its previously configured grants.
        assert not velora.permissions.has_permission(meta, 'create')
