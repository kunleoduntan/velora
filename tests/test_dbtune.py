"""One-click database tuning: indexes, statistics, space; never the data."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from velora import db, dbtune, get_list, new_doc
from velora.db.tables import get_table
from velora.api import create_app
from velora.exceptions import PermissionDenied
from velora.permissions import Session, session_as

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


def test_tune_recreates_missing_indexes_and_leaves_the_data_alone(site):
    new_doc("Customer Group", group_name="Retail").insert()
    for n in ("Acme", "Bola"):
        new_doc("Customer", customer_name=n, customer_group="Retail").insert()
    before = get_list("Customer", fields=["name", "customer_name"], ignore_permissions=True, order_by="name asc")
    with db.get_engine().begin() as c:
        names = [i["name"] for i in inspect(c).get_indexes(get_table("Customer").name) if i["name"].startswith("ix_")]
        assert names, "the Customer table should have link indexes"
        c.execute(text(f'DROP INDEX "{names[0]}"'))
    plan = dbtune.preview()
    assert any(names[0] in x for x in plan["indexes_to_create"])
    out = dbtune.tune()
    assert any(names[0] in x for x in out["indexes_created"]) and out["statistics_refreshed"] and out["size_after"] > 0
    assert get_list("Customer", fields=["name", "customer_name"], ignore_permissions=True, order_by="name asc") == before
    again = dbtune.tune()
    assert again["indexes_created"] == []                                                  # a second run finds nothing to do


def test_only_a_system_manager_may_tune(site):
    with session_as(Session(user="sam", roles={"Sales User"})):
        with pytest.raises(PermissionDenied):
            dbtune.tune()
        with pytest.raises(PermissionDenied):
            dbtune.preview()


def test_routes(site):
    api = TestClient(create_app(auto_init=False))
    assert api.get("/api/database/tune", headers=ADMIN).status_code == 200
    r = api.post("/api/database/tune", headers=ADMIN)
    assert r.status_code == 200 and r.json()["data" if "data" in r.json() else "database"] is not None
    assert api.post("/api/database/tune", headers={"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}).status_code == 403
