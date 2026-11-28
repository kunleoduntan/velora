import pytest
import velora
from velora import activity, get_doc, new_doc
from sqlalchemy import select
from velora import db

def _customer(**kw):
    kw.setdefault("customer_name","Audit Customer")
    return new_doc("Customer",**kw).insert()

def test_document_lifecycle_is_automatically_audited(site):
    with velora.session_as(velora.Session("lifecycle.user",frozenset({"System Manager"}))):
        customer=_customer()
        customer.credit_limit=250
        customer.save()
        order=new_doc("Sales Order",customer=customer.name,items=[{"description":"Service","qty":1,"rate":10}]).insert()
        order.submit()
        get_doc("Sales Order",order.name).cancel()
        with pytest.raises(Exception, match="cancelled documents must remain"):
            get_doc("Sales Order",order.name).delete()
    feed=activity.feed(limit=100)
    matching=[x for x in feed["items"] if x["document_name"] in {customer.name,order.name}]
    types={(x["doctype"],x["document_name"],x["event_type"]) for x in matching}
    assert ("Customer",customer.name,"created") in types
    assert ("Customer",customer.name,"updated") in types
    assert ("Sales Order",order.name,"created") in types
    assert ("Sales Order",order.name,"submitted") in types
    assert ("Sales Order",order.name,"cancelled") in types
    assert ("Sales Order",order.name,"deleted") not in types
    update=next(x for x in matching if x["document_name"]==customer.name and x["event_type"]=="updated")
    assert "credit_limit" in update["changed_fields"]
    assert update["actor"]=="lifecycle.user"

def test_failed_document_write_does_not_leave_activity_event(site):
    with velora.session_as(velora.Session("lifecycle.user",frozenset({"System Manager"}))):
        before=activity.feed(limit=100)["total"]
        with pytest.raises(Exception):
            new_doc("Customer",customer_name="").insert()
        after=activity.feed(limit=100)["total"]
    assert after==before


def test_workflow_start_and_approval_are_automatically_audited(site):
    from velora.workflows import save_definition, start, act
    from velora.permissions import Session, session_as
    doc=_customer(customer_name="Workflow Audit Customer")
    save_definition({"name":"Audit Approval Flow","doctype":"Customer","initial_state":"Pending",
      "states":[{"name":"Pending"},{"name":"Approved","is_final":True}],
      "transitions":[{"action":"Approve","from_state":"Pending","to_state":"Approved",
        "roles":["Approver"],"final":True}]})
    instance=start("Audit Approval Flow","Customer",doc.name)
    with session_as(Session("workflow.approver",frozenset({"Approver","Sales User"}))):
        act(instance["id"],"Approve")
    events=[x for x in activity.feed(limit=100)["items"] if x["document_name"]==doc.name]
    assert any(x["event_type"]=="workflow" and "started" in x["title"] for x in events)
    assert any(x["event_type"]=="approval" and x["actor"]=="workflow.approver" for x in events)
    assert any(x["event_type"]=="approval" and "action: Approve" in x["title"] for x in events)
