import velora_governance.api as governance_api


class FakeFrappe:
    def __init__(self, rows):
        self.rows = rows
        self.permissions = []
    def has_permission(self, doctype, perm, name=None):
        self.permissions.append((doctype, perm, name))
        return True
    def get_count(self, doctype, filters=None):
        if filters and 'execution_status' in filters:
            return sum(r['execution_status'] == filters['execution_status'] for r in self.rows)
        return len(self.rows)
    def get_list(self, doctype, filters=None, fields=None, order_by=None, limit_page_length=None, limit_start=0):
        rows = self.rows
        if filters and 'execution_status' in filters:
            rows = [r for r in rows if r['execution_status'] == filters['execution_status']]
        return rows[limit_start:limit_start + limit_page_length]


def test_monitor_history_paging_has_total_and_next_flag(monkeypatch):
    rows = [{'name': f'GAE-{i}', 'execution_status': 'Completed', 'action_type': 'Reminder'} for i in range(1, 6)]
    fake = FakeFrappe(rows)
    monkeypatch.setattr(governance_api, 'frappe', fake)
    page = governance_api.get_governance_automation_execution_history_page(limit=2, offset=2)
    assert page['total'] == 5
    assert [r['name'] for r in page['rows']] == ['GAE-3', 'GAE-4']
    assert page['has_more'] is True
    assert page['offset'] == 2


def test_monitor_history_paging_status_filter(monkeypatch):
    rows = [{'name': 'A', 'execution_status': 'Failed'}, {'name': 'B', 'execution_status': 'Completed'}]
    fake = FakeFrappe(rows)
    monkeypatch.setattr(governance_api, 'frappe', fake)
    page = governance_api.get_governance_automation_execution_history_page(status='Failed', limit=50, offset=0)
    assert page['total'] == 1
    assert page['rows'][0]['name'] == 'A'
    assert page['has_more'] is False


def test_monitor_history_paging_clamps_limit_and_offset(monkeypatch):
    fake = FakeFrappe([])
    monkeypatch.setattr(governance_api, 'frappe', fake)
    page = governance_api.get_governance_automation_execution_history_page(limit=999, offset=-4)
    assert page['limit'] == 200
    assert page['offset'] == 0
