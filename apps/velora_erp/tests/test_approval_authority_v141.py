"""Authority for the few non-approval powers is configuration, not code (document approval itself is a GUI workflow, see test_finance_workflow_v284)."""
import pytest

import velora
from velora.permissions import PermissionDenied, Session, session_as
from velora_erp.finance import approval_authority as aa


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'aa.db'}", apps=[], developer_mode=True)
    velora.init(); velora.migrate()


def test_document_approval_is_not_an_authority_setting_any_more():
    assert not any(k.startswith("financial_document.decide") or k in ("financial_document.reset", "account_correction.apply", "budget.adjust") for k in aa.DEFAULTS)


def test_reversing_a_posted_document_is_no_longer_a_power_because_posted_documents_are_cancelled():
    assert "financial_document.reverse" not in aa.DEFAULTS


def test_defaults_name_the_remaining_powers(site):
    assert aa.roles_for("budget.override") == ()                                       # nothing is restricted by code
    assert aa.is_authorised("hr_policy.approve", user="x", roles=("Finance Manager",))
    assert aa.is_authorised("hr_policy.approve", user="x", roles=("Accountant",))   # anyone whose role permissions allow it


def test_a_company_can_name_its_own_role(site):
    aa.set_authority("budget.override", ["Head of Finance"])
    assert aa.is_authorised("budget.override", user="hof", roles=("Head of Finance",))
    assert not aa.is_authorised("budget.override", user="fm", roles=("Finance Manager",))


def test_administrator_keeps_authority_so_a_bad_setting_cannot_lock_the_company_out(site):
    aa.set_authority("budget.override", ["Nobody Role"])
    assert aa.is_authorised("budget.override", user="Administrator", roles=())


def test_only_a_system_manager_can_change_authority(site):
    with session_as(Session("fm@x.test", frozenset({"Finance Manager"}))):
        with pytest.raises(PermissionDenied):
            aa.set_authority("budget.override", ["Finance Manager"])


def test_rejects_unknown_actions_and_empty_role_lists(site):
    with pytest.raises(aa.ApprovalAuthorityError):
        aa.set_authority("made.up", ["X"])
    with pytest.raises(aa.ApprovalAuthorityError):
        aa.set_authority("budget.override", [" ", ""])


def test_reset_returns_to_defaults(site):
    aa.set_authority("budget.override", ["Head of Finance"])
    aa.reset_authority("budget.override")
    assert aa.roles_for("budget.override") == aa.DEFAULTS["budget.override"] == ()
