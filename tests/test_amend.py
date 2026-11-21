"""Cancel -> amend -> submit (the ERPNext way), and duplicate."""
import pytest
from fastapi.testclient import TestClient

from velora import get_doc, new_doc
from velora.api import create_app
from velora.document import amend
from velora.exceptions import DocStatusError, PermissionDenied, ValidationError
from velora.meta.registry import registry
from velora.permissions import Session, session_as

from test_notify import ns  # noqa: F401  (apps: demo + notifications)

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


def order(customer, qty=2, rate=100, submit=True):
    c = new_doc("Customer", customer_name=customer, credit_limit=1).insert()
    so = new_doc("Sales Order", customer=c.name, order_date="2026-03-02")
    so.append("items", {"description": "Widget", "qty": qty, "rate": rate})
    so.append("items", {"description": "Gadget", "qty": 1, "rate": 50})
    so.insert()
    return so.submit() if submit else so


def amendment_of(so):
    """Do what the Desk does: fetch the pre-filled values, then save them as a new document."""
    p = amend.copy_values("Sales Order", so.name, "amend")
    return new_doc("Sales Order", **p["values"]).insert(), p


# ============================== the field ==============================
def test_every_submittable_doctype_gets_a_hidden_read_only_amended_from_link_and_nothing_else_does(site):
    so = registry.get("Sales Order")
    f = so.get_field("amended_from")
    assert f.fieldtype == "Link" and f.options == "Sales Order" and f.read_only and f.hidden
    assert [x.fieldname for x in so.fields].count("amended_from") == 1
    assert registry.get("Customer").get_field("amended_from") is None                                                  # not submittable: no amending
    assert registry.get("Sales Order Item").get_field("amended_from") is None                                           # a child table never amends


# ============================== cancel -> amend -> submit ==============================
def test_the_full_cycle_a_mistake_is_fixed_by_cancelling_and_amending(site):
    so = order("Acme")
    so.cancel()
    assert get_doc("Sales Order", so.name).docstatus == 2 and amend.amendment_of("Sales Order", so.name) is None
    p = amend.copy_values("Sales Order", so.name, "amend")
    assert p["mode"] == "amend" and p["source"] == so.name and p["amended_from"] == so.name and p["suggested_name"] == f"{so.name}-1"
    v = p["values"]
    assert v["customer"] == so.customer and v["amended_from"] == so.name and "name" not in v and "docstatus" not in v and "creation" not in v and "owner" not in v
    assert [(r["description"], r["qty"], r["rate"]) for r in v["items"]] == [("Widget", 2, 100), ("Gadget", 1, 50)]      # the lines come along ...
    assert all(not ({"name", "idx", "parent", "parentfield", "parenttype", "creation"} & set(r)) for r in v["items"])  # ... as NEW rows
    v["items"][0]["qty"] = 5                                                                                           # the correction
    new = new_doc("Sales Order", **v).insert()
    assert new.name == f"{so.name}-1" and new.docstatus == 0 and new.amended_from == so.name
    new.submit()
    assert get_doc("Sales Order", new.name).docstatus == 1 and get_doc("Sales Order", new.name).items[0].qty == 5
    assert get_doc("Sales Order", so.name).docstatus == 2 and get_doc("Sales Order", so.name).items[0].qty == 2        # the cancelled original is exactly as it was
    assert amend.amendment_of("Sales Order", so.name) == new.name


def test_amendments_are_numbered_in_sequence_and_a_document_is_amended_only_once(site):
    so = order("Acme")
    so.cancel()
    first, _ = amendment_of(so)
    assert first.name == f"{so.name}-1"
    with pytest.raises(ValidationError, match=f"{so.name} has already been amended as {so.name}-1. Amend that one instead"):
        amend.copy_values("Sales Order", so.name, "amend")                                                              # no second amendment of the same document
    with pytest.raises(ValidationError, match="already been amended"):
        new_doc("Sales Order", customer=so.customer, order_date="2026-03-02", amended_from=so.name, items=[{"description": "x", "qty": 1, "rate": 1}]).insert()   # not even by going round the Desk
    first.submit().cancel()
    second, p = amendment_of(first)
    assert p["suggested_name"] == f"{so.name}-2" and second.name == f"{so.name}-2"                                      # SO-1 -> SO-1-1 would be confusing: it counts on
    second.submit().cancel()
    assert amendment_of(second)[0].name == f"{so.name}-3"


def test_only_a_cancelled_document_can_be_amended(site):
    draft, sub = order("A", submit=False), order("B")
    with pytest.raises(ValidationError, match="a draft \\(just edit it\\)"):
        amend.copy_values("Sales Order", draft.name, "amend")
    with pytest.raises(ValidationError, match="submitted \\(cancel it first\\)"):
        amend.copy_values("Sales Order", sub.name, "amend")
    with pytest.raises(ValidationError, match="does not exist"):
        amend.check_amendment("Sales Order", "SO-9999")
    c = new_doc("Customer", customer_name="Plain").insert()
    with pytest.raises(ValidationError, match="not submittable"):
        amend.copy_values("Customer", c.name, "amend")
    with pytest.raises(ValidationError, match="must be 'amend' or 'duplicate'"):
        amend.copy_values("Sales Order", sub.name, "clone")
    with pytest.raises(ValidationError, match="child row"):
        amend.copy_values("Sales Order Item", "x", "duplicate")
    bad = new_doc("Sales Order", customer=sub.customer, order_date="2026-03-02", amended_from=sub.name, items=[{"description": "x", "qty": 1, "rate": 1}])
    with pytest.raises(ValidationError, match="submitted \\(cancel it first\\)"):
        bad.insert()                                                                                                     # the rule is in the engine, not just the screen


def test_cancelling_twice_is_refused_and_the_amendment_can_be_cancelled_too(site):
    so = order("Acme")
    so.cancel()
    with pytest.raises(DocStatusError):
        so.cancel()
    new, _ = amendment_of(so)
    new.submit()
    new.cancel()
    assert get_doc("Sales Order", new.name).docstatus == 2                                                             # the correction can itself be corrected


# ============================== duplicate ==============================
def test_duplicate_copies_any_document_into_a_new_unlinked_draft_form(site):
    so = order("Acme")
    p = amend.copy_values("Sales Order", so.name, "duplicate")
    assert p["mode"] == "duplicate" and p["amended_from"] is None and p["suggested_name"] is None and "amended_from" not in p["values"]
    new = new_doc("Sales Order", **p["values"]).insert()
    assert new.name != so.name and new.docstatus == 0 and not new.get("amended_from") and [r.qty for r in new.items] == [2, 1]
    assert get_doc("Sales Order", so.name).docstatus == 1                                                              # the source is untouched
    amend.copy_values("Sales Order", new.name, "duplicate")                                                            # drafts and submitted ones alike


def test_a_duplicate_does_not_copy_values_that_must_be_unique(ns):
    """A Notification Rule is named by its (unique) rule_name: the copy must be given a new one."""
    from test_notify import rule
    r = rule("Original", channels=("In-App", "Email"), recipients=(("User", "alice@acme.ng"),), subject="Hi {{ doc.customer_name }}")
    p = amend.copy_values("Notification Rule", r.name, "duplicate")
    v = p["values"]
    assert v["rule_name"] is None and v["subject"] == "Hi {{ doc.customer_name }}" and v["ref_doctype"] == "Customer"        # the name is chosen again; the rest is copied
    assert [c["channel"] for c in v["channels"]] == ["In-App", "Email"] and v["recipients"][0]["value"] == "alice@acme.ng"
    assert all("name" not in c and "parent" not in c for c in v["channels"])
    v["rule_name"] = "Copy of original"
    assert new_doc("Notification Rule", **v).insert().name == "Copy of original"


# ============================== permissions ==============================
def test_you_need_to_be_able_to_read_and_create_to_copy(site, monkeypatch):
    so = order("Acme")
    so.cancel()
    with session_as(Session("nobody", frozenset({"Stranger"}))):
        with pytest.raises(Exception, match="(?i)permission|not allowed|may not"):
            amend.copy_values("Sales Order", so.name, "duplicate")                                                       # cannot even read it
    import velora.permissions as perms
    real = perms.has_permission
    monkeypatch.setattr(perms, "has_permission", lambda meta, ptype, *a, **k: False if ptype == "create" else real(meta, ptype, *a, **k))        # a user who can read but not create
    for mode in ("amend", "duplicate"):
        with pytest.raises(PermissionDenied, match=f"You may not create Sales Order, so you cannot {mode} one"):
            amend.copy_values("Sales Order", so.name, mode)


# ============================== the API ==============================
def test_the_api_serves_copies_and_says_what_a_cancelled_document_became(site):
    so = order("Acme")
    c = TestClient(create_app(auto_init=False))
    r = c.get(f"/api/resource/Sales Order/{so.name}/copy?mode=duplicate", headers=ADMIN)
    assert r.status_code == 200 and r.json()["data"]["values"]["customer"] == so.customer and c.get(f"/api/resource/Sales Order/{so.name}/copy", headers=ADMIN).json()["data"]["mode"] == "duplicate"
    r = c.get(f"/api/resource/Sales Order/{so.name}/copy?mode=amend", headers=ADMIN)
    assert r.status_code == 422 and "submitted (cancel it first)" in r.json()["message"]
    assert c.get(f"/api/resource/Sales Order/{so.name}/amended-to", headers=ADMIN).json()["data"] == {"amended_to": None}
    so.cancel()
    assert c.get(f"/api/resource/Sales Order/{so.name}/copy?mode=amend", headers=ADMIN).json()["data"]["suggested_name"] == f"{so.name}-1"
    new, _ = amendment_of(so)
    assert c.get(f"/api/resource/Sales Order/{so.name}/amended-to", headers=ADMIN).json()["data"] == {"amended_to": new.name}
    r = c.get(f"/api/resource/Sales Order/{so.name}/copy?mode=amend", headers=ADMIN)
    assert r.status_code == 422 and f"already been amended as {new.name}" in r.json()["message"]
    assert c.get(f"/api/resource/Sales Order/{so.name}/copy?mode=amend").status_code == 401
    assert c.get("/api/resource/Sales Order/SO-9999/copy?mode=duplicate", headers=ADMIN).status_code == 404
    assert c.get("/api/resource/Sales Order/SO-9999/amended-to", headers=ADMIN).status_code == 404


# ============================== what stands in the way of cancelling ==============================
def test_submitted_documents_that_link_to_a_document_are_listed_and_stop_its_cancel(site):
    from velora import linked
    from velora.exceptions import LinkedDocumentsError
    so = order("Linked Co")
    deps = linked.submitted_dependents("Customer", so.customer)
    assert [(d["doctype"], d["name"]) for d in deps] == [("Sales Order", so.name)]
    cust = get_doc("Customer", so.customer)
    with pytest.raises(LinkedDocumentsError, match=f"Sales Order {so.name}"):
        linked.check_can_cancel(cust)
    assert linked.preview("Customer", so.customer)["dependents"][0]["name"] == so.name
    so.cancel()
    assert linked.submitted_dependents("Customer", so.customer) == []                       # a cancelled document no longer stands in the way
    linked.check_can_cancel(cust)


def test_cancel_all_cancels_the_chain_in_one_go_and_is_all_or_nothing(site):
    from velora import linked
    so = order("Chain Co")
    done = linked.cancel_all("Sales Order", so.name, "entered twice")
    assert done == [{"doctype": "Sales Order", "name": so.name}]
    assert get_doc("Sales Order", so.name).docstatus == 2
    client = TestClient(create_app(auto_init=False))
    so2 = order("Chain Two")
    r = client.get(f"/api/linked-documents/Sales Order/{so2.name}", headers=ADMIN)
    assert r.status_code == 200 and r.json()["data"]["dependents"] == []
    r = client.post(f"/api/cancel-all/Sales Order/{so2.name}", headers=ADMIN, json={"reason": "duplicate"})
    assert r.status_code == 200 and r.json()["data"]["cancelled"][0]["name"] == so2.name
