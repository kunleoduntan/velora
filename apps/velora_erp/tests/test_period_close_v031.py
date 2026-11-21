from datetime import date

import pytest
import velora
from velora import get_doc, new_doc
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as

from test_finance_reporting import setup_finance, teardown

MAKER = Session("period-maker@example.test", frozenset({"Accountant"}))
APPROVER = Session("period-approver@example.test", frozenset({"Finance Manager"}))


def _close_doc(period_name):
    from velora_erp.finance.doctype.financial_period_close.financial_period_close import CHECKLIST
    return new_doc(
        "Financial Period Close",
        financial_period=period_name,
        close_date=date(date.today().year + 1, 3, 31),
        checklist=[{
            "item_code": code,
            "description": description,
            "completed": 1,
            "evidence_reference": f"EVIDENCE-{code}",
            "reviewer_notes": "Reviewed and reconciled.",
        } for code, description in CHECKLIST],
        close_notes="Period-end review completed.",
    )


def test_period_close_requires_independent_approval_and_full_checklist(tmp_path):
    setup_finance(tmp_path)
    try:
        period_name = f"FY-{date.today().year}-APR-P01"
        from wf_helpers import install_approval, decide
        install_approval("Financial Period Close")
        with session_as(MAKER):
            close = _close_doc(period_name).insert()
            assert close.system_checks_passed == 1 and close.approval_status == "Pending"
            close.checklist[0].completed = 0
            close.save()
        decide("Financial Period Close", close.name, "Approve", APPROVER)
        with session_as(APPROVER):
            close = get_doc("Financial Period Close", close.name)
            with pytest.raises(ValidationError, match="Complete every period-end review checklist"):
                close.submit()
            close = get_doc("Financial Period Close", close.name)
            close.checklist[0].completed = 1
            # Approved evidence is locked until the workflow reopens it.
            with pytest.raises(ValidationError, match="locked"):
                close.save()
        decide("Financial Period Close", close.name, "Reopen", APPROVER, "evidence completed")
        with session_as(APPROVER):
            close = get_doc("Financial Period Close", close.name)
            close.checklist[0].completed = 1
            close.save()
        decide("Financial Period Close", close.name, "Approve", APPROVER)
        with session_as(APPROVER):
            close = get_doc("Financial Period Close", close.name)
            close.submit()
            period = get_doc("Financial Period", period_name)
            assert period.status == "Closed"
            assert str(period.closed_on) == str(date(date.today().year + 1, 3, 31))
    finally:
        teardown()


def test_financial_period_cannot_be_closed_directly(tmp_path):
    setup_finance(tmp_path)
    try:
        period_name = f"FY-{date.today().year}-APR-P01"
        with session_as(APPROVER):
            period = get_doc("Financial Period", period_name)
            period.status = "Closed"
            period.closed_on = date.today()
            with pytest.raises(ValidationError, match="must be closed through an approved Financial Period Close"):
                period.save()
    finally:
        teardown()
