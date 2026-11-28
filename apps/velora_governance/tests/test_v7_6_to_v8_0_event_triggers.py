from datetime import date
from velora_governance.governance.services.governance_automation_event_trigger import enqueue_overdue_exception

class Repo:
    def __init__(self): self.items = {}
    def insert_if_absent(self, payload):
        key = payload['idempotency_key']
        if key in self.items: return {'created': False}
        self.items[key] = payload; return {'created': True}

CONFIG = {
    'automation_enabled': 1,
    'owner_field_mapping': {},
    'recipient_overrides': {},
}

def test_event_trigger_queues_overdue_active_board_action():
    repo = Repo()
    doc = {'doctype':'Board Action','name':'BA-001','due_date':'2026-11-20',
            'action_status':'Open','action_title':'Approve policy','assigned_owner':'user@example.com',
            'modified':'2026-11-26 10:00:00'}
    result = enqueue_overdue_exception(doc, repository=repo, today=date(2026,11,26), configuration=CONFIG)
    assert result['status'] == 'queued'
    queued = next(iter(repo.items.values()))['action']
    assert queued['action_type'] == 'notification'
    assert queued['trigger_kind'] == 'overdue_exception'
    assert queued['owner'] == 'user@example.com'
    assert queued['days_until_due'] == -6


def test_event_trigger_suppresses_duplicate_event():
    repo = Repo()
    doc = {'doctype':'Board Action','name':'BA-002','due_date':'2026-11-20',
            'action_status':'Open','action_title':'Approve policy','assigned_owner':'user@example.com',
            'modified':'2026-11-26 10:00:00'}
    first = enqueue_overdue_exception(doc, repository=repo, today=date(2026,11,26), configuration=CONFIG)
    second = enqueue_overdue_exception(doc, repository=repo, today=date(2026,11,26), configuration=CONFIG)
    assert first['status'] == 'queued'
    assert second['status'] == 'duplicate_suppressed'


def test_event_trigger_ignores_non_overdue_or_terminal_items():
    repo = Repo()
    doc = {'doctype':'Board Action','name':'BA-003','due_date':'2026-11-30',
            'action_status':'Open','assigned_owner':'user@example.com'}
    result = enqueue_overdue_exception(doc, repository=repo, today=date(2026,11,26), configuration=CONFIG)
    assert result['reason'] == 'not_overdue_active_item'
    assert not repo.items


def test_event_trigger_fail_closed_when_automation_disabled():
    doc = {'doctype':'Board Action','name':'BA-004','due_date':'2026-11-20',
            'action_status':'Open','assigned_owner':'user@example.com'}
    config = {**CONFIG, 'automation_enabled':0}
    result = enqueue_overdue_exception(doc, repository=Repo(), today=date(2026,11,26), configuration=config)
    assert result['reason'] == 'automation_disabled'


def test_event_trigger_allowlist_blocks_unknown_doctype():
    result = enqueue_overdue_exception({'doctype':'User','name':'x'}, repository=Repo(), configuration=CONFIG)
    assert result['reason'] == 'doctype_not_allowlisted'
