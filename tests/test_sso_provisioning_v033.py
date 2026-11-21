import pytest
from sqlalchemy import create_engine, insert
from velora.controlplane import models as m
from velora.controlplane.sso_provisioning import SSOProvisioner
from velora.exceptions import AuthenticationRequired, CompanyAccessDenied, ValidationError

class Plane:
    def __init__(self):
        self.engine = create_engine('sqlite://')
        m.cp_metadata.create_all(self.engine)
        self.events = []
    def audit(self, *args, **kwargs):
        self.events.append((args, kwargs))

@pytest.fixture
def service():
    p = Plane()
    with p.engine.begin() as c:
        c.execute(insert(m.tenant).values(id='t1', name='Tenant 1', status='active'))
        c.execute(insert(m.tenant).values(id='t2', name='Tenant 2', status='active'))
        c.execute(insert(m.company).values(id='co1', name='Company 1', code='C1', db_engine='sqlite', tenant_id='t1', status='active', db_name='x'))
        c.execute(insert(m.user).values(id='u1', email='u@example.com', password_hash='none', is_active=True))
        c.execute(insert(m.user_company).values(user_id='u1', company_id='co1', roles=[]))
    return SSOProvisioner(p)

def test_identity_requires_explicit_link_and_tenant(service):
    identity = {'issuer':'https://idp.example','subject':'immutable-123','email':'u@example.com'}
    with pytest.raises(AuthenticationRequired):
        service.resolve_identity(identity, 't1')
    service.link_existing(issuer=identity['issuer'], subject=identity['subject'], user_id='u1')
    assert service.resolve_identity(identity, 't1') == 'u1'
    with pytest.raises(CompanyAccessDenied):
        service.resolve_identity(identity, 't2')
    with pytest.raises(ValidationError):
        service.link_existing(issuer=identity['issuer'], subject=identity['subject'], user_id='another')

def test_session_lifecycle(service):
    token = service.issue_session('u1', 't1')
    assert service.list_sessions('u1')[0]['active_company_id'] == 'co1'
    from velora.controlplane.identity import _token_hash
    assert service.revoke_session('u1', _token_hash(token))
    assert service.list_sessions('u1') == []
    service.issue_session('u1','t1')
    service.issue_session('u1','t1')
    assert service.revoke_all_sessions('u1') == 2
    with pytest.raises(CompanyAccessDenied):
        service.issue_session('u1','t2')
