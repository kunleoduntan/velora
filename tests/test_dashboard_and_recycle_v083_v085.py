import pytest
import velora
from velora import new_doc, get_doc
from velora.dashboards import _formula
from velora.document import recycle_bin
from velora.permissions import Session, session_as
from velora.exceptions import ValidationError

def test_dashboard_formula_safe_arithmetic():
    assert _formula("revenue - cost + tax * 2", {"revenue": 100, "cost": 20, "tax": 5}) == 90
    assert _formula("(a / b) * 100", {"a": 25, "b": 50}) == 50
    with pytest.raises(ValidationError): _formula("__import__('os')", {})
    with pytest.raises(ValidationError): _formula("unknown + 1", {})

def test_deleted_draft_is_archived_and_recalled(site):
    with session_as(Session("recycle.admin", frozenset({"System Manager"}))):
        doc=new_doc("Customer", customer_name="Recycle Bin Test").insert()
        name=doc.name
        doc.delete(reason="Duplicate draft created in error")
        result=recycle_bin.listing(limit=20,doctype="Customer",status="Deleted")
        item=next(x for x in result["items"] if x["document_name"]==name)
        restored=recycle_bin.restore(item["id"])
        assert restored["restored"] is True
        assert get_doc("Customer",name).customer_name=="Recycle Bin Test"
        assert recycle_bin.get_item(item["id"])["status"]=="Restored"
        assert recycle_bin.get_item(item["id"])["reason"]=="Duplicate draft created in error"

def test_deleted_draft_restore_preserves_child_rows(site):
    with session_as(Session("recycle.admin", frozenset({"System Manager"}))):
        customer=new_doc("Customer",customer_name="Recycle Child Customer").insert()
        order=new_doc("Sales Order",customer=customer.name,items=[{"description":"Archive item","qty":2,"rate":"12.50"}]).insert()
        name=order.name
        order.delete()
        result=recycle_bin.listing(limit=20,doctype="Sales Order",status="Deleted")
        item=next(x for x in result["items"] if x["document_name"]==name)
        recycle_bin.restore(item["id"])
        restored=get_doc("Sales Order",name)
        assert restored.items[0].description=="Archive item"
        assert restored.items[0].rate == __import__("decimal").Decimal("12.50")

def test_cancellation_reason_is_recorded_in_audit(site):
    from velora import activity
    with session_as(Session("cancel.admin",frozenset({"System Manager"}))):
        customer=new_doc("Customer",customer_name="Cancellation Reason Customer").insert()
        order=new_doc("Sales Order",customer=customer.name,items=[{"description":"Reason item","qty":1,"rate":5}]).insert()
        order.submit()
        get_doc("Sales Order",order.name).cancel(reason="Incorrect customer reference")
        event=next(x for x in activity.feed(limit=100,doctype="Sales Order",event_type="cancelled")["items"] if x["document_name"]==order.name)
        assert event["metadata"]["reason"]=="Incorrect customer reference"
        assert event["metadata"]["reason_missing"] is False
