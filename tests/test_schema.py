from sqlalchemy import inspect, text

import velora
from velora import db
from velora.db.tables import safe_identifier, table_name


def test_migrate_is_idempotent(site):
    assert velora.migrate() == []


def test_tables_and_columns_created(site):
    with db.transaction() as conn:
        insp = inspect(conn)
        cols = {c["name"] for c in insp.get_columns("tab_customer")}
        child = {c["name"] for c in insp.get_columns("tab_customer_contact")}
    assert {"name", "customer_name", "credit_limit", "status", "docstatus", "modified"} <= cols
    assert {"parent", "parenttype", "parentfield", "idx"} <= child
    assert "contacts" not in cols  # Table fields have no column


def test_missing_column_is_added_and_dry_run_does_not_apply(site):
    with db.transaction() as conn:
        conn.execute(text("ALTER TABLE tab_customer DROP COLUMN credit_limit"))
    plan = velora.migrate(dry_run=True)
    assert any("ADD COLUMN" in p and "credit_limit" in p for p in plan)
    with db.transaction() as conn:
        assert "credit_limit" not in {c["name"] for c in inspect(conn).get_columns("tab_customer")}
    velora.migrate()
    with db.transaction() as conn:
        assert "credit_limit" in {c["name"] for c in inspect(conn).get_columns("tab_customer")}


def test_identifier_policy_is_deterministic_and_short():
    long = "A" * 200
    a, b = safe_identifier(long), safe_identifier(long)
    assert a == b and len(a) <= 63
    assert table_name("Sales Order") == "tab_sales_order"
