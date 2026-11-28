import pytest
from sqlalchemy import create_engine, insert
from types import SimpleNamespace
from velora.controlplane import models as m
from velora.controlplane.user_admin import UserAdministration
from velora.exceptions import CompanyAccessDenied, ValidationError

class Plane:
    def __init__(self):
        self.engine = create_engine('sqlite://')
        m.cp_metadata.create_all(self.engine)
        self.events = []
    def audit(self, *args, **kwargs): self.events.append((args, kwargs))

@pytest.fixture
def setup():
    p = Plane()
    admin = SimpleNamespace(is_platform_admin=True, email='root@example.com')
    nonadmin = SimpleNamespace(is_platform_admin=False, email='user@example.com')
    with p.engine.begin() as c:
        c.execute(insert(m.tenant).values(id='t1', name='Tenant', status='active'))
        c.execute(insert(m.company).values(id='co1', tenant_id='t1', name='Company', code='C1', db_engine='sqlite', db_name='x', status='active'))
        c.execute(insert(m.user).values(id='admin', email='root@example.com', full_name='Root', password_hash='x', is_active=True, is_platform_admin=True))
    return p, UserAdministration(p), admin, nonadmin

def test_provisioning_requires_admin_and_defaults_inactive(setup):
    p, svc, admin, nonadmin = setup
    with pytest.raises(CompanyAccessDenied): svc.provision_user(nonadmin, email='new@example.com')
    u = svc.provision_user(admin, email='new@example.com', full_name='New User')
    assert u['is_active'] is False
    assert svc.list_users(admin, include_inactive=False)[0]['email'] == 'root@example.com'
    svc.set_user_active(admin, u['id'], True)
    assert svc.list_users(admin)[1]['is_active'] is True

def test_profile_membership_and_revoke(setup):
    p, svc, admin, _ = setup
    u = svc.provision_user(admin, email='new@example.com', activate=True)
    svc.update_profile(admin, u['id'], full_name='Updated Name')
    svc.grant_company_membership(admin, u['id'], 'co1', ['Accounts User'])
    assert svc.list_user_memberships(admin, u['id'])[0]['roles'] == ['Accounts User']
    assert svc.revoke_company_membership(admin, u['id'], 'co1')
    assert svc.list_user_memberships(admin, u['id']) == []

def test_suspension_and_validation(setup):
    p, svc, admin, _ = setup
    u = svc.provision_user(admin, email='new@example.com', activate=True)
    with pytest.raises(ValidationError): svc.update_profile(admin, u['id'], email='bad-email')
    svc.set_user_active(admin, u['id'], False)
    assert next(x for x in svc.list_users(admin) if x['id'] == u['id'])['is_active'] is False
