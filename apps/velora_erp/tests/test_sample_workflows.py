"""Sample approval workflows are only offered; installing one saves it switched off, and nothing changes until a company switches one on."""
import velora
from velora import workflows
from velora.permissions import session_as, Session

from test_cash_transactions import setup_cash
from velora_erp.finance.workflow_samples import SAMPLES, sample_name

SM = Session("sysman@example.test", frozenset({"System Manager"}))


def test_samples_are_offered_not_installed_and_install_switched_off(tmp_path):
    setup_cash(tmp_path)
    try:
        offered = {t["name"]: t for t in workflows.workflow_templates()}
        assert {sample_name(d) for d in SAMPLES} <= set(offered)
        assert workflows.list_definitions() == [], "nothing is installed by itself"
        for d in SAMPLES:
            assert not workflows.is_managed(d)
        with session_as(SM):
            done = workflows.install_templates([sample_name("Stock Entry"), sample_name("Salary Slip")])
        assert len(done) == 2
        assert all(not w["enabled"] for w in workflows.list_definitions())
        assert not workflows.is_managed("Stock Entry") and not workflows.is_managed("Salary Slip")
    finally:
        velora.shutdown()


def test_a_sample_on_a_document_without_an_approval_field_gates_submit_through_the_built_in_state(tmp_path):
    """Sales Order has no approval field. Its sample keeps state in the built-in Workflow State, so it works without Customize Form."""
    from datetime import date
    from velora import new_doc, get_doc
    from velora.exceptions import ValidationError
    import pytest
    accounts, customer, _ = setup_cash(tmp_path)
    try:
        maker = Session("maker@example.test", frozenset({"Accountant", "Sales User"}))
        boss = Session("boss@example.test", frozenset({"Finance Manager", "Accountant", "Sales User"}))
        with session_as(SM):
            workflows.install_templates([sample_name("Sales Order")])
            d = next(w for w in workflows.list_definitions() if w["name"] == sample_name("Sales Order"))
            assert d["state_field"] == "workflow_state" and not d["enabled"]
            workflows.save_definition({**{k: d[k] for k in ("name", "doctype", "initial_state", "states", "transitions", "state_field")}, "enabled": True})
        assert workflows.is_managed("Sales Order")
        with session_as(maker):
            so = new_doc("Sales Order", document_date=date.today(), party=customer.name, currency="NGN", exchange_rate=1,
                         lines=[{"description": "Desk", "quantity": 1, "uom": "Each", "rate": 100}]).insert(ignore_permissions=True)
        assert so.workflow_state == "Pending"
        with session_as(boss), pytest.raises(ValidationError):          # even someone allowed to submit must wait for approval
            get_doc("Sales Order", so.name).submit()
        inst = workflows.document_workflow("Sales Order", so.name)["instance_id"]
        with session_as(boss):
            workflows.act(inst, "Approve", "ok")
        assert get_doc("Sales Order", so.name, ignore_permissions=True).workflow_state == "Approved"
        with session_as(boss):
            get_doc("Sales Order", so.name).submit()
        assert get_doc("Sales Order", so.name, ignore_permissions=True).docstatus == 1
    finally:
        velora.shutdown()
