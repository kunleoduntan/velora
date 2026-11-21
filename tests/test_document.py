import threading
from decimal import Decimal

import pytest

import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import (DocStatusError, DoesNotExistError, DuplicateEntryError, LinkValidationError,
                               MandatoryError, PermissionDenied, TimestampMismatchError, ValidationError)

SALES = velora.Session("sam", frozenset({"Sales User"}))
NOBODY = velora.Session("nobody", frozenset())


def customer(**kw):
    kw.setdefault("customer_name", "Acme Ltd")
    return new_doc("Customer", **kw).insert()


def test_series_naming_defaults_and_coercion(site):
    c1, c2 = customer(), customer(customer_name="  Beta  ", credit_limit="1500.50")
    assert (c1.name, c2.name) == ("CUST-0001", "CUST-0002")
    assert c1.status == "Active"                       # default applied
    assert c2.customer_name == "Beta"                  # controller validate ran
    assert c2.credit_limit == Decimal("1500.50")        # str -> Currency
    assert get_doc("Customer", "CUST-0002").credit_limit == Decimal("1500.5")


def test_empty_string_is_stored_as_null(site):
    c = customer(email="")
    assert get_doc("Customer", c.name).email is None


def test_validation_errors(site):
    with pytest.raises(MandatoryError):
        new_doc("Customer").insert()
    with pytest.raises(ValidationError, match="Credit limit"):
        customer(credit_limit=-1)
    with pytest.raises(ValidationError, match="must be one of"):
        customer(status="Weird")
    with pytest.raises(LinkValidationError):
        customer(customer_group="Nope")
    with pytest.raises(ValidationError, match="unknown field"):
        new_doc("Customer", bogus=1)
    with pytest.raises(ValidationError, match="not a valid Int|not a valid Currency"):
        customer(credit_limit="abc")


def test_failed_insert_rolls_back_series_number(site):
    with pytest.raises(LinkValidationError):
        customer(customer_group="Nope")
    assert customer().name == "CUST-0001"              # no gap


def test_field_naming_and_duplicates(site):
    new_doc("Customer Group", group_name="Retail").insert()
    with pytest.raises(DuplicateEntryError):
        new_doc("Customer Group", group_name="Retail").insert()


def test_child_tables_roundtrip_and_diff_save(site):
    c = customer(contacts=[{"contact_name": "Ada"}, {"contact_name": "Bola", "email": "b@x.ng"}])
    loaded = get_doc("Customer", c.name)
    assert [r.contact_name for r in loaded.contacts] == ["Ada", "Bola"]
    assert [r.idx for r in loaded.contacts] == [1, 2]
    ada_name = loaded.contacts[0].name
    loaded.contacts = [loaded.contacts[0]]
    loaded.append("contacts", {"contact_name": "Chi"})
    loaded.save()
    again = get_doc("Customer", c.name)
    assert [r.contact_name for r in again.contacts] == ["Ada", "Chi"]
    assert again.contacts[0].name == ada_name          # existing row kept, not recreated
    with pytest.raises(MandatoryError, match="row 1"):
        again.contacts[0].contact_name = None
        again.save()


def test_optimistic_locking(site):
    c = customer()
    a, b = get_doc("Customer", c.name), get_doc("Customer", c.name)
    a.email = "a@x.ng"
    a.save()
    b.email = "b@x.ng"
    with pytest.raises(TimestampMismatchError):
        b.save()


def test_track_changes_writes_audit_version(site):
    from sqlalchemy import select
    from velora import db
    from velora.db.system import version
    c = customer()
    c.credit_limit = 10
    c.save()
    with db.transaction() as conn:
        rows = conn.execute(select(version.c.data).where(version.c.docname == c.name)).scalars().all()
    assert rows and "credit_limit" in rows[0]["changed"]


def sales_order(cust, **kw):
    return new_doc("Sales Order", customer=cust, items=[{"description": "Widget", "qty": 3, "rate": "100.10"}], **kw)


def test_submit_cancel_lifecycle(site):
    c = customer()
    so = sales_order(c.name).insert()
    assert so.name == "SO-00001" and so.total == Decimal("300.30")
    assert so.items[0].amount == Decimal("300.30")
    so.submit()
    assert get_doc("Sales Order", so.name).docstatus == 1
    d = get_doc("Sales Order", so.name)
    d.items[0].rate = 1
    with pytest.raises(DocStatusError, match="cannot be edited"):
        d.save()
    with pytest.raises(DocStatusError):
        d.delete()
    with pytest.raises(DocStatusError, match="draft"):
        get_doc("Sales Order", so.name).submit()
    get_doc("Sales Order", so.name).cancel()
    assert get_doc("Sales Order", so.name).docstatus == 2
    with pytest.raises(DocStatusError, match="cancelled documents must remain"):
        get_doc("Sales Order", so.name).delete()


def test_submit_blocked_customer_rolls_back(site):
    c = customer(status="Blocked")
    so = sales_order(c.name).insert()
    with pytest.raises(ValidationError, match="blocked"):
        so.submit()
    assert get_doc("Sales Order", so.name).docstatus == 0


def test_delete_blocked_when_linked(site):
    c = customer()
    sales_order(c.name).insert()
    with pytest.raises(LinkValidationError, match="linked from Sales Order"):
        get_doc("Customer", c.name).delete()


def test_get_list_filters_sorting_and_injection_safety(site):
    for n in ("Zed", "Alpha", "Mid"):
        customer(customer_name=n)
    rows = get_list("Customer", fields=["name", "customer_name"], order_by="customer_name asc")
    assert [r["customer_name"] for r in rows] == ["Alpha", "Mid", "Zed"]
    assert len(get_list("Customer", filters=[["customer_name", "like", "%d"]])) == 2   # Zed, Mid
    assert len(get_list("Customer", filters={"status": "Active"}, limit=2)) == 2
    with pytest.raises(ValidationError):
        get_list("Customer", filters=[["name; DROP TABLE x", "=", 1]])
    with pytest.raises(ValidationError):
        get_list("Customer", order_by="name; DROP TABLE x")


def test_permissions_enforced_in_engine(site):
    c = customer()
    with velora.session_as(SALES):
        assert get_doc("Customer", c.name).name == c.name
        new_doc("Customer", customer_name="By Sales").insert()
        with pytest.raises(PermissionDenied):
            get_doc("Customer", c.name).delete()
        with pytest.raises(PermissionDenied):
            new_doc("Customer Group", group_name="X").insert()
    with velora.session_as(NOBODY):
        with pytest.raises(PermissionDenied):
            get_list("Customer")
        with pytest.raises(PermissionDenied):
            get_doc("Customer", c.name)


def test_owner_and_modified_by_stamped_from_session(site):
    with velora.session_as(SALES):
        c = new_doc("Customer", customer_name="Stamped").insert()
    assert get_doc("Customer", c.name).owner == "sam"


def test_missing_document(site):
    with pytest.raises(DoesNotExistError):
        get_doc("Customer", "CUST-9999")


def test_series_is_unique_under_concurrency(site):
    if site.db_url.startswith("sqlite"):
        pytest.skip("SQLite serialises writers; concurrency is verified on PostgreSQL")
    names, errors = [], []

    def work():
        try:
            names.append(customer().name)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(names)) == 12


def test_a_failed_submit_leaves_the_document_ready_to_retry(site):
    """Regression: a failed submit left a stale `modified` timestamp, so the retry died with a misleading 'modified by someone else'."""
    from velora.exceptions import ValidationError
    cust = new_doc("Customer", customer_name="Blocked Co", status="Blocked").insert()
    so = new_doc("Sales Order", customer=cust.name, items=[{"description": "a", "qty": 1, "rate": 5}]).insert()
    before = (so.modified, so.docstatus, [dict(r.__dict__) for r in so.items])
    for _ in range(2):                                                                   # fails the same way every time ...
        with pytest.raises(ValidationError, match="blocked customer"):
            so.submit()
        assert (so.modified, so.docstatus, [dict(r.__dict__) for r in so.items]) == before   # ... and nothing in memory has drifted
    c = get_doc("Customer", cust.name)
    c.status = "Active"
    c.save()
    so.submit()                                                                          # fixed: the SAME object now submits cleanly
    assert so.docstatus == 1 and get_doc("Sales Order", so.name).docstatus == 1


def test_a_failed_insert_does_not_leave_a_name_behind(site):
    from velora.exceptions import ValidationError
    so = new_doc("Sales Order", customer="NO-SUCH-CUSTOMER", items=[{"description": "a", "qty": 1, "rate": 5}])
    with pytest.raises(Exception):
        so.insert()
    assert so.name is None and so.is_new()
    cust = new_doc("Customer", customer_name="Late Co").insert()
    so.customer = cust.name
    so.insert()                                                                          # the same object inserts after the problem is fixed
    assert so.name and not so.is_new()
    assert ValidationError
