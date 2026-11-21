from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import velora
from velora import db, get_count, get_doc, get_group_by, get_list, new_doc
from velora.api import create_app
from velora.bulk import bulk_action
from velora.exceptions import PermissionDenied, ValidationError

SALES = {"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}
ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


def cust(name, **kw):
    return new_doc("Customer", customer_name=name, **kw).insert()


def seed(n=6):
    new_doc("Customer Group", group_name="Retail").insert()
    new_doc("Customer Group", group_name="Wholesale").insert()
    for i in range(n):
        cust(f"Cust {i}", status="Active" if i % 3 else "Blocked", customer_group="Retail" if i < 4 else "Wholesale",
             credit_limit=i * 100 if i else None)


def test_extended_filter_operators(site):
    seed()
    names = lambda f: sorted(r["customer_name"] for r in get_list("Customer", filters=f, fields=["customer_name"]))
    assert names([["customer_name", "not like", "%1"]]) == ["Cust 0", "Cust 2", "Cust 3", "Cust 4", "Cust 5"]
    assert names([["credit_limit", "between", [100, 300]]]) == ["Cust 1", "Cust 2", "Cust 3"]
    assert names([["credit_limit", "is", "not set"]]) == ["Cust 0"]
    assert len(names([["credit_limit", "is", "set"]])) == 5
    assert names([["status", "in", ["Blocked"]]]) == ["Cust 0", "Cust 3"]
    assert names([["status", "not in", ["Active"]]]) == ["Cust 0", "Cust 3"]
    assert get_count("Customer", [["customer_group", "=", "Wholesale"]]) == 2


def test_typed_filters_work_on_every_backend(site):
    seed(2)
    new_doc("Sales Order", customer="CUST-0001", order_date="2026-03-15", items=[{"description": "a", "qty": 1, "rate": 5}]).insert()
    assert len(get_list("Sales Order", filters=[["order_date", ">=", "2026-03-01"]])) == 1
    assert len(get_list("Sales Order", filters=[["order_date", "between", ["2026-01-01", "2026-03-15"]]])) == 1
    assert len(get_list("Sales Order", filters=[["order_date", "<", "2026-03-15"]])) == 0
    today = date.today().isoformat()
    assert len(get_list("Sales Order", filters=[["creation", "between", [today, today]]])) == 1   # date-only 'to' = whole day
    with pytest.raises(ValidationError, match="not a valid Date"):
        get_list("Sales Order", filters=[["order_date", "=", "tomorrow-ish"]])
    with pytest.raises(ValidationError, match="only applies to text"):
        get_list("Customer", filters=[["credit_limit", "like", "%1%"]])
    with pytest.raises(ValidationError, match="needs a list"):
        get_list("Customer", filters=[["status", "in", "Active"]])
    with pytest.raises(ValidationError, match="between"):
        get_list("Customer", filters=[["credit_limit", "between", [1]]])


def test_group_by_counts(site):
    seed()
    rows = {r["value"]: r["count"] for r in get_group_by("Customer", "status")}
    assert rows == {"Active": 4, "Blocked": 2}
    assert {r["value"]: r["count"] for r in get_group_by("Customer", "customer_group", [["status", "=", "Active"]])} == {"Retail": 2, "Wholesale": 2}
    with pytest.raises(ValidationError):
        get_group_by("Customer", "customer_name")          # free text is not groupable


def test_bulk_actions_are_per_document(site):
    seed(3)
    so = new_doc("Sales Order", customer="CUST-0002", items=[{"description": "a", "qty": 1, "rate": 5}]).insert()
    res = bulk_action("Customer", "delete", ["CUST-0001", "CUST-0002", "CUST-0003", "CUST-0001"])
    by = {r["name"]: r for r in res}
    assert len(res) == 3 and by["CUST-0001"]["ok"] and by["CUST-0003"]["ok"]
    assert not by["CUST-0002"]["ok"] and "linked from Sales Order" in by["CUST-0002"]["error"]
    assert get_count("Customer") == 1                         # the two good deletes committed despite one failure
    res = bulk_action("Sales Order", "submit", [so.name, "SO-99999"])
    assert [r["ok"] for r in res] == [True, False] and get_doc("Sales Order", so.name).docstatus == 1
    bulk_action("Customer", "update", ["CUST-0002"], {"status": "Inactive"})
    assert get_doc("Customer", "CUST-0002").status == "Inactive"
    with pytest.raises(ValidationError):
        bulk_action("Customer", "update", ["CUST-0002"], {"owner": "x"})
    with pytest.raises(ValidationError):
        bulk_action("Customer", "explode", ["x"])


def test_bulk_and_group_by_over_api_respect_permissions(site):
    c = TestClient(create_app(auto_init=False))
    seed(2)
    r = c.post("/api/bulk/Customer", json={"action": "update", "names": ["CUST-0001"], "values": {"status": "Blocked"}}, headers=SALES)
    assert r.status_code == 200 and r.json()["data"][0]["ok"]
    r = c.post("/api/bulk/Customer", json={"action": "delete", "names": ["CUST-0001"]}, headers=SALES)   # Sales User cannot delete
    assert r.json()["data"][0]["ok"] is False and "no 'delete' permission" in r.json()["data"][0]["error"]
    assert c.get("/api/group_by/Customer", params={"field": "status"}, headers=SALES).json()["data"]
    assert c.get("/api/group_by/Customer", params={"field": "customer_name"}, headers=SALES).status_code == 422


def test_aggregate_sums_all_matching_rows_not_just_a_page(site):
    from velora import get_aggregate
    seed(6)                                          # credit limits: None,100,200,300,400,500; Blocked at i=0,3
    assert get_aggregate("Customer", ["credit_limit"]) == {"credit_limit": 1500.0}
    assert get_aggregate("Customer", ["credit_limit"], [["status", "=", "Active"]]) == {"credit_limit": 100.0 + 200 + 400 + 500}
    assert get_aggregate("Customer", ["credit_limit"], [["status", "=", "Inactive"]]) == {"credit_limit": None}      # nothing matches
    with pytest.raises(ValidationError, match="numeric"):
        get_aggregate("Customer", ["customer_name"])
    with pytest.raises(ValidationError):
        get_aggregate("Customer", [])
    with pytest.raises(ValidationError):
        get_aggregate("Customer", ["name; drop table x"])


def test_aggregate_endpoint_and_permissions(site):
    c = TestClient(create_app(auto_init=False))
    seed(4)
    r = c.get("/api/aggregate/Customer", params={"fields": '["credit_limit"]', "filters": '[["status","=","Active"]]'}, headers=SALES)
    assert r.status_code == 200 and r.json()["data"] == {"credit_limit": 100.0 + 200}      # the two Active customers
    assert c.get("/api/aggregate/Customer", params={"fields": '["email"]'}, headers=SALES).status_code == 422
    assert c.get("/api/aggregate/Customer", params={"fields": '["credit_limit"]'}, headers={"X-Velora-User": "n", "X-Velora-Roles": ""}).status_code == 403


def test_contains_search_ignores_case_on_every_database(site):
    seed()
    names = lambda v, op="like": sorted(r["customer_name"] for r in get_list("Customer", filters=[["customer_name", op, v]], fields=["customer_name"]))
    assert names("%ust 1%") == names("%UST 1%") == names("%Ust 1%") == ["Cust 1"]
    assert len(names("%CUST%")) == len(names("%cust%")) == 6
    assert names("%CUST 1%", "not like") == [n for n in names("%cust%") if n != "Cust 1"]
