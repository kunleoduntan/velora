import json
from datetime import date
from velora_governance.governance.services.governance_automation_configuration import DEFAULT_CONFIGURATION, validate_configuration, load_configuration
from velora_governance.governance.services.governance_automation_scheduler import collect_due_items


def test_default_configuration_is_valid_and_normalized():
    result = validate_configuration(DEFAULT_CONFIGURATION)
    assert result["valid"] is True
    assert result["normalized"]["reminder_days_before"] == [0, 1, 3, 7, 14, 30]
    assert result["normalized"]["max_attempts"] == 5


def test_configuration_rejects_out_of_range_and_duplicate_values():
    result = validate_configuration({**DEFAULT_CONFIGURATION,
        "reminder_days_before": "0,7,7,9999", "max_attempts": 99,
        "max_batch_size": 1000, "retry_base_minutes": 0})
    assert not result["valid"]
    assert len(result["errors"]) >= 4


def test_owner_mapping_accepts_only_allowlisted_fields():
    good = validate_configuration({**DEFAULT_CONFIGURATION,
        "owner_field_mapping": json.dumps({"Board Action": "assigned_owner"})})
    bad = validate_configuration({**DEFAULT_CONFIGURATION,
        "owner_field_mapping": json.dumps({"Board Action": "created_by"})})
    assert good["valid"]
    assert not bad["valid"]


def test_loader_returns_safe_default_if_configuration_not_seeded():
    api = {"get_list": lambda *a, **kw: [], "get_doc": lambda *a, **kw: None}
    cfg = load_configuration(api)
    assert cfg["automation_enabled"] == 1
    assert cfg["max_batch_size"] == 100


def test_loader_disables_automation_on_invalid_persisted_configuration():
    class Doc:
        def as_dict(self):
            return {**DEFAULT_CONFIGURATION, "max_attempts": 99}
    api = {"get_list": lambda *a, **kw: [{"name": "GAC"}], "get_doc": lambda *a, **kw: Doc()}
    cfg = load_configuration(api)
    assert cfg["automation_enabled"] == 0
    assert cfg["configuration_errors"]


def test_owner_mapping_is_applied_to_collection_fields():
    rows = {"Board Action": [{"name": "BA-2", "due_date": "2026-11-26", "action_status": "Open",
        "action_title": "Review", "assigned_owner": "secretary@example.test", "governance_entity": "GE-1"}]}
    class API:
        def get_list(self, doctype, **kwargs):
            return rows.get(doctype, [])
        def get_doc(self, *a, **kw):
            raise AssertionError
        def new_doc(self, *a, **kw):
            raise AssertionError
    items = collect_due_items(API(), today=date(2026, 11, 26), owner_field_mapping={"Board Action": "assigned_owner"})
    assert items[0]["owner"] == "secretary@example.test"


def test_recipient_override_validation_requires_known_source_and_user_identifier():
    valid = validate_configuration({**DEFAULT_CONFIGURATION,
        "recipient_overrides": json.dumps({"Annual Return": "company.secretary@example.test"})})
    invalid = validate_configuration({**DEFAULT_CONFIGURATION,
        "recipient_overrides": json.dumps({"Unknown DocType": "user@example.test"})})
    empty = validate_configuration({**DEFAULT_CONFIGURATION,
        "recipient_overrides": json.dumps({"Annual Return": " "})})
    assert valid["valid"]
    assert not invalid["valid"]
    assert not empty["valid"]


def test_annual_return_ownerless_candidate_can_use_explicit_fallback_recipient():
    from velora_governance.governance.services.governance_automation_scheduler import generate_and_persist_actions
    rows = {"Annual Return": [{"name": "AR-2026", "due_date": "2026-11-26", "annual_return_status": "Ready",
        "reporting_year": "2026", "governance_entity": "GE-1"}]}
    class API:
        def get_list(self, doctype, **kwargs):
            return rows.get(doctype, [])
        def get_doc(self, *a, **kw):
            raise AssertionError
        def new_doc(self, *a, **kw):
            raise AssertionError
    class Repository:
        def __init__(self): self.rows = []
        def insert_if_absent(self, record):
            self.rows.append(record)
            return {"created": True, "record": record}
    repo = Repository()
    result = generate_and_persist_actions(api=API(), repository=repo, today=date(2026, 11, 26),
        recipient_overrides={"Annual Return": "company.secretary@example.test"})
    assert result["persisted"] == 1
    assert repo.rows[0]["action"]["owner"] == "company.secretary@example.test"
    assert repo.rows[0]["action"]["recipient_fallback"] is True
