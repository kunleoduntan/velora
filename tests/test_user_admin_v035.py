from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select
from velora.controlplane import models as m
from velora.controlplane.user_admin import UserAdministration
from velora.exceptions import CompanyAccessDenied


def test_session_admin_listing_and_revoke_is_token_safe():
    from sqlalchemy import create_engine
    engine = create_engine('sqlite://')
    m.cp_metadata.create_all(engine)

    class Plane:
        def __init__(self): self.engine = engine; self.events = []
        def audit(self, *args, **kwargs): self.events.append((args, kwargs))

    plane = Plane()
    admin = SimpleNamespace(is_platform_admin=True, email='admin@example.com')
    nonadmin = SimpleNamespace(is_platform_admin=False, email='user@example.com')
    now = datetime.now(timezone.utc)
    with engine.begin() as c:
        c.execute(insert(m.user).values(id='u1', email='person@example.com', full_name='Person',
            password_hash='x', is_active=True, is_platform_admin=False))
        c.execute(insert(m.session).values(token_hash='a'*64, user_id='u1', created_on=now,
            expires_on=now+timedelta(hours=1), last_seen=now, active_company_id='co1',
            ip='127.0.0.1', user_agent='test-agent'))
        c.execute(insert(m.session).values(token_hash='b'*64, user_id='u1', created_on=now,
            expires_on=now+timedelta(hours=2), last_seen=now, active_company_id=None,
            ip='127.0.0.2', user_agent='other-agent'))

    svc = UserAdministration(plane)
    sessions = svc.list_user_sessions(admin, 'u1')
    assert len(sessions) == 2
    assert all('token_hash' not in row for row in sessions)
    assert all('user_id' not in row for row in sessions)
    assert svc.revoke_session(admin, 'u1', 'a'*64) is True
    assert svc.revoke_session(admin, 'u1', 'a'*64) is False
    assert len(svc.list_user_sessions(admin, 'u1')) == 1
    assert any(event[0][0] == 'admin.session_revoked' for event in plane.events)
    with pytest.raises(CompanyAccessDenied):
        svc.list_user_sessions(nonadmin, 'u1')
    with pytest.raises(CompanyAccessDenied):
        svc.revoke_session(nonadmin, 'u1', 'b'*64)


def test_platform_admin_routes_registered_and_console_served():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from velora.api.platform_admin import install_platform_admin_routes

    from sqlalchemy import create_engine
    from types import SimpleNamespace
    app = FastAPI()
    install_platform_admin_routes(app, SimpleNamespace(engine=create_engine('sqlite://'))) 
    paths = {route.path for route in app.routes}
    assert '/api/platform/users' in paths
    assert '/api/platform/users/{user_id}/memberships' in paths
    assert '/api/platform/users/{user_id}/sessions' in paths
    response = TestClient(app).get('/platform/users/manage')
    assert response.status_code == 200
    assert 'User administration' in response.text
    assert 'X-Velora-Request' in response.text
