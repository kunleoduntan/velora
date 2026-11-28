from types import SimpleNamespace
from unittest.mock import patch
from datetime import date, timedelta
import pytest
from velora.exceptions import ValidationError
from velora_admin.administration.doctype.approval_delegation.approval_delegation import ApprovalDelegation
from velora_admin.administration import sla


def test_delegation_self_assignment_rejected():
    doc=object.__new__(ApprovalDelegation)
    doc.delegator_user="a"; doc.delegate_user="a"; doc.start_date=date.today().isoformat(); doc.end_date=(date.today()+timedelta(days=1)).isoformat(); doc.status="Draft"; doc.doctype_scope="Request"
    with pytest.raises(ValidationError, match="cannot delegate"):
        doc.validate()


def test_delegation_end_date_must_follow_start_date():
    doc=object.__new__(ApprovalDelegation)
    doc.delegator_user="a"; doc.delegate_user="b"; doc.start_date="2026-12-10"; doc.end_date="2026-12-01"; doc.status="Draft"; doc.doctype_scope="Request"
    with pytest.raises(ValidationError, match="before its start"):
        doc.validate()


def test_daily_sla_marks_overdue_and_escalated():
    doc=SimpleNamespace(name="REQ-OVERDUE",sla_due_datetime="2026-01-01 00:00:00",sla_status="On Track",escalated=0,escalated_on=None,save=lambda **kwargs:None)
    with patch.object(sla,"registry",SimpleNamespace(exists=lambda name: True)), patch.object(sla,"get_list",return_value=[{"name":"REQ-OVERDUE"}]), patch.object(sla,"get_doc",return_value=doc), patch.object(sla,"_notify_escalation") as notify:
        result=sla.daily_maintenance()
    assert result["scanned"]==1
    assert result["updated"]==1
    assert result["escalated"]==1
    assert doc.sla_status=="Overdue"
    assert doc.escalated==1
    notify.assert_called_once_with(doc)
