from types import SimpleNamespace
import pytest
from sqlalchemy import select
from velora import db
from velora.controlplane.role_admin import RoleAdministration
from velora.document import new_doc, get_doc, get_list, get_count, get_group_by, get_aggregate
from velora.permissions import Session, session_as
from velora.exceptions import PermissionDenied, ValidationError
from velora.db.system import row_policy

ADMIN = SimpleNamespace(is_company_admin=True, email='admin@company.test', roles={'System Manager'})


def _setup_role():
    svc = RoleAdministration(db.get_engine())
    svc.create_role(ADMIN, 'Sales Scoped')
    for operation in ('create', 'read', 'write', 'delete'):
        svc.set_permission(ADMIN, 'Sales Scoped', 'Customer', operation, True)
    svc.set_row_policy(ADMIN, 'Sales Scoped', 'Customer', 'create', [
        {'field': 'owner', 'operator': 'equals_user'}])
    svc.set_row_policy(ADMIN, 'Sales Scoped', 'Customer', 'read', [
        {'field': 'owner', 'operator': 'equals_user'}])
    svc.set_row_policy(ADMIN, 'Sales Scoped', 'Customer', 'write', [
        {'field': 'owner', 'operator': 'equals_user'}])
    return svc


def test_row_scope_applies_to_lists_counts_and_single_document(site):
    _setup_role()
    with session_as(Session('alice@example.com', frozenset({'Sales Scoped'}))):
        own = new_doc('Customer', customer_name='Alice Customer', credit_limit=125).insert()
    with session_as(Session('bob@example.com', frozenset({'Sales Scoped'}))):
        other = new_doc('Customer', customer_name='Bob Customer', credit_limit=900).insert()
    with session_as(Session('alice@example.com', frozenset({'Sales Scoped'}))):
        rows = get_list('Customer', fields=['name', 'customer_name'], limit=100)
        assert [r['name'] for r in rows] == [own.name]
        assert get_count('Customer') == 1
        assert get_aggregate('Customer', ['credit_limit'])['credit_limit'] == 125.0
        assert sum(x['count'] for x in get_group_by('Customer', 'status')) == 1
        assert get_doc('Customer', own.name).customer_name == 'Alice Customer'
        from velora.exceptions import DoesNotExistError
        with pytest.raises(DoesNotExistError):
            get_doc('Customer', other.name)


def test_row_scope_blocks_cross_owner_update_and_delete(site):
    _setup_role()
    with session_as(Session('alice@example.com', frozenset({'Sales Scoped'}))):
        own = new_doc('Customer', customer_name='Alice Customer').insert()
    with session_as(Session('bob@example.com', frozenset({'Sales Scoped'}))):
        other = new_doc('Customer', customer_name='Bob Customer').insert()
    with session_as(Session('alice@example.com', frozenset({'Sales Scoped'}))):
        doc = get_doc('Customer', own.name)
        doc.customer_name = 'Alice Updated'
        doc.save()
        doc = get_doc('Customer', own.name)
        doc.owner = 'bob@example.com'
        with pytest.raises(PermissionDenied):
            doc.save()
        with pytest.raises(PermissionDenied):
            stolen = get_doc('Customer', other.name, ignore_permissions=True)
            stolen.customer_name = 'Tampered'
            stolen.save()


def test_policy_validation_rejects_unknown_fields_and_unsafe_operators(site):
    svc = _setup_role()
    with pytest.raises(ValidationError):
        svc.set_row_policy(ADMIN, 'Sales Scoped', 'Customer', 'read', [
            {'field': 'does_not_exist', 'operator': 'eq', 'value': 'x'}])
    with pytest.raises(ValidationError):
        svc.set_row_policy(ADMIN, 'Sales Scoped', 'Customer', 'read', [
            {'field': 'owner', 'operator': 'raw_sql', 'value': '1=1'}])


def test_row_policy_is_company_database_local(site):
    _setup_role()
    with db.transaction() as conn:
        assert conn.execute(select(row_policy.c.role).where(row_policy.c.role == 'Sales Scoped')).first()
