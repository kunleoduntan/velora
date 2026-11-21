"""v2.84: approval is a GUI-managed workflow, not code.

* a company with no workflow for a document type has no approval step (documents are approved when saved);
* with a workflow, the approval field is owned by the workflow, the document locks once approved, submission waits for it
  and who may approve is whatever the company configured, with maker-checker where the workflow asks for it;
* the sample workflows install inactive and can be changed per company.
"""
from datetime import date

import pytest
import velora
from velora import get_doc, new_doc
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import Session, session_as
from velora import workflows

from test_cash_transactions import setup_cash, MAKER, APPROVER

HEAD = Session("head.of.finance@example.test", frozenset({"Auditor"}))     # this company lets its Auditor role approve (it can read Receipts)


def receipt(accounts):
    with session_as(MAKER):
        return new_doc("Receipt", receipt_date=date.today(), posting_date=date.today(), purpose="Other Income", currency="NGN", exchange_rate=1,
                       cash_account=accounts["1000"].name, narration="Sundry income", lines=[{"account": accounts["4000"].name, "amount": 10}]).insert()


def install(doctype="Receipt", roles=("Finance Manager",), **kw):
    from velora_erp.finance.workflow_templates import _definition
    d = {**_definition(doctype, list(roles)), "enabled": True, **kw}
    with session_as(Session("Administrator", frozenset({"System Manager"}))):
        return workflows.save_definition(d)


def act(doc, action, who, comment=""):
    inst = workflows.document_workflow(doc.doctype, doc.name)["instance_id"]
    with session_as(who):
        return workflows.act(inst, action, comment)


def test_a_document_type_with_no_workflow_has_no_approval_step(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        r = receipt(accounts)
        assert r.approval_status == "Approved" and not workflows.is_managed("Receipt")
        with session_as(APPROVER):
            get_doc("Receipt", r.name).submit(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_with_a_workflow_a_new_document_waits_and_cannot_be_approved_by_typing_or_submitted(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        install()
        r = receipt(accounts)
        assert r.approval_status == "Pending"
        bar = workflows.document_workflow("Receipt", r.name)
        assert bar["state"] == "Pending" and bar["instance_id"] and not bar["submit_ready"]
        with session_as(APPROVER):                                     # typing "Approved" into the form must not work
            d = get_doc("Receipt", r.name); d.approval_status = "Approved"
            with pytest.raises(ValidationError, match="controlled by this document's approval workflow"):
                d.save()
            with pytest.raises(ValidationError, match="cannot be submitted until its approval workflow reaches Approved"):
                get_doc("Receipt", r.name).submit(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_the_approver_is_whoever_the_company_named_and_never_the_maker(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        install(roles=("Auditor",))                                    # this company: not the Finance Manager
        r = receipt(accounts)
        with pytest.raises(PermissionDenied):
            act(r, "Approve", APPROVER)                                # a Finance Manager is not an approver here
        maker_as_approver = Session(MAKER.user, frozenset({"Accountant", "Auditor"}))
        with pytest.raises(PermissionDenied, match="separation of duties"):
            act(r, "Approve", maker_as_approver)                       # the maker cannot approve their own document
        with session_as(APPROVER):
            assert {a["action"]: a["can_act"] for a in workflows.document_workflow("Receipt", r.name)["actions"]} == {"Approve": False, "Reject": False}
        with session_as(HEAD):
            bar = workflows.document_workflow("Receipt", r.name)
            assert {a["action"]: a["can_act"] for a in bar["actions"]} == {"Approve": True, "Reject": True}
        act(r, "Approve", HEAD, "ok")
        done = get_doc("Receipt", r.name)
        assert done.approval_status == "Approved" and done.approved_by == HEAD.user and done.approved_on
    finally:
        velora.shutdown()


def test_approved_content_is_locked_until_the_workflow_reopens_it(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        install()
        r = receipt(accounts)
        act(r, "Approve", APPROVER)
        with session_as(MAKER):
            d = get_doc("Receipt", r.name); d.narration = "changed after approval"
            with pytest.raises(ValidationError, match="locked"):
                d.save()
        assert workflows.document_workflow("Receipt", r.name)["locked"] is True
        act(r, "Reopen", APPROVER, "needs a correction")
        reopened = get_doc("Receipt", r.name)
        assert reopened.approval_status == "Pending" and not reopened.approved_by
        with session_as(MAKER):
            d = get_doc("Receipt", r.name); d.narration = "corrected"; d.save()
        act(r, "Approve", APPROVER)
        with session_as(APPROVER):
            get_doc("Receipt", r.name).submit(ignore_permissions=True)
        assert get_doc("Receipt", r.name).docstatus == 1
    finally:
        velora.shutdown()


def test_a_rejected_document_cannot_be_submitted_and_can_be_reopened(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        install()
        r = receipt(accounts)
        act(r, "Reject", APPROVER, "wrong account")
        assert get_doc("Receipt", r.name).rejected_by == APPROVER.user
        with session_as(APPROVER):
            with pytest.raises(ValidationError):
                get_doc("Receipt", r.name).submit(ignore_permissions=True)
        act(r, "Reopen for correction", APPROVER)
        assert get_doc("Receipt", r.name).approval_status == "Pending"
    finally:
        velora.shutdown()


def test_sample_workflows_are_installed_inactive_and_change_nothing(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        offered = {t["doctype"]: t for t in workflows.workflow_templates()}
        assert {"Receipt", "Payroll Run", "Financial Voucher", "Financial Budget"} <= set(offered)
        assert all(t["installed"] for t in offered.values())                               # present for the company to read and edit...
        assert not any(workflows.is_managed(d) for d in offered)                           # ...but none switched on
        assert receipt(accounts).approval_status == "Approved"
        with session_as(Session("Administrator", frozenset({"System Manager"}))):
            assert workflows.install_templates(["Receipt Approval"]) == []                   # never overwrites a company's own edits
        assert "Payroll Manager" in offered["Payroll Run"]["approvers"] and "Payroll Manager" not in offered["Receipt"]["approvers"]
    finally:
        velora.shutdown()


def test_disabling_the_workflow_returns_the_type_to_no_approval_step(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        install()
        assert workflows.is_managed("Receipt")
        install(enabled=False)
        assert not workflows.is_managed("Receipt")
        assert receipt(accounts).approval_status == "Approved"
    finally:
        velora.shutdown()


def test_a_document_that_existed_before_the_workflow_can_be_put_into_it(tmp_path):
    accounts, _, _ = setup_cash(tmp_path)
    try:
        r = receipt(accounts)                                           # saved with no workflow: Approved
        install()
        bar = workflows.document_workflow("Receipt", r.name)
        assert bar["can_start"] is False                                # already decided; it is not silently dragged back to Pending
    finally:
        velora.shutdown()
