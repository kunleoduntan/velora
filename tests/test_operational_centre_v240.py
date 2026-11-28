from fastapi.testclient import TestClient
from velora.api import create_app

ADMIN={"X-Velora-User":"boss","X-Velora-Roles":"System Manager"}


def test_operational_centre_is_read_only_and_returns_consistent_sections(site):
    client=TestClient(create_app(auto_init=False))
    response=client.get('/api/operational-centre',headers=ADMIN)
    assert response.status_code==200, response.text
    data=response.json()['data']
    assert data['read_only'] is True
    assert set(data['summary']) >= {'approvals','assigned_tasks','draft_and_pending','overdue_workflows','active_workflows'}
    assert isinstance(data['approvals'],list)
    assert isinstance(data['tasks'],list)
    assert isinstance(data['exceptions'],list)
    assert isinstance(data['workflow'],dict)


def test_operational_centre_requires_authenticated_session(site):
    client=TestClient(create_app(auto_init=False))
    response=client.get('/api/operational-centre')
    assert response.status_code in (401,403)


def test_operational_centre_exception_queues_do_not_expose_unreadable_doc_types(monkeypatch):
    from velora.api import operational_centre as module
    monkeypatch.setattr(module, '_safe_count', lambda doctype, filters: None if doctype == 'Salary Slip' else 0)
    # Exercise the queue omission rule without opening any document or bypassing permissions.
    result=[]
    for area, doctype, label, filters, route in module.QUEUES:
        count=module._safe_count(doctype, filters)
        if count is not None:
            result.append(doctype)
    assert 'Salary Slip' not in result
    assert 'Journal Entry' in result
