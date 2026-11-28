"""JSON -> JSONB on PostgreSQL: new columns, safe conversion of old databases, GIN index, containment filters."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import text

import velora
from velora import db, get_list, new_doc
from velora.db import get_engine
from velora.exceptions import ValidationError
from velora.settings import get_setting, set_setting

from test_notify import ns  # noqa: F401  (the notifications fixture: both databases, with velora_notify installed)


def on_pg():
    return get_engine().dialect.name == "postgresql"


def raw(sql):
    with db.transaction() as c:
        return c.execute(text(sql)).all()


def coltype(table, col):
    return raw(f"select data_type from information_schema.columns where table_name = '{table}' and column_name = '{col}'")[0][0]


def delivery(**kw):
    return new_doc("Notification Delivery", rule="r", channel="Email", recipient="a@b.co", subject="s", status="Queued", attempts=0, **kw).insert(ignore_permissions=True)


def test_new_json_columns_are_jsonb_on_postgresql_and_json_elsewhere(ns):
    if on_pg():
        for t, c in (("velora_setting", "value"), ("velora_export_log", "detail"), ("tab_notification_delivery", "payload")):
            assert coltype(t, c) == "jsonb", (t, c)
    else:
        assert "JSON" in str(get_engine().dialect.type_descriptor(__import__("velora.db.types", fromlist=["x"]).json_type())).upper()
    set_setting("x.y", {"b": 1, "a": [1, 2, {"c": None}]})
    assert get_setting("x.y") == {"a": [1, 2, {"c": None}], "b": 1}                                                  # values round-trip exactly (key ORDER is not kept on JSONB)


def test_an_older_database_with_plain_json_is_converted_once_with_data_kept(ns):
    if not on_pg():
        pytest.skip("PostgreSQL only")
    set_setting("keep.me", {"unicode": "Ọláolúwa ₦", "n": [1, 2.5, None], "nested": {"deep": True}})
    with db.transaction() as c:                                                                                       # simulate a database created before this release (no GIN index, plain json)
        c.exec_driver_sql("DROP INDEX gin_tab_notification_delivery_payload")
        c.exec_driver_sql("ALTER TABLE velora_setting ALTER COLUMN value TYPE json USING value::json")
        c.exec_driver_sql("ALTER TABLE tab_notification_delivery ALTER COLUMN payload TYPE json USING payload::json")
    assert coltype("velora_setting", "value") == "json"
    plan = velora.migrate(dry_run=True)
    assert any(p.startswith("ALTER TABLE velora_setting ALTER COLUMN value TYPE JSONB USING") and p.endswith("::jsonb") for p in plan)
    assert coltype("velora_setting", "value") == "json"                                                              # a dry run changes nothing
    done = velora.migrate()
    assert any("TYPE JSONB" in p for p in done) and coltype("velora_setting", "value") == "jsonb" and coltype("tab_notification_delivery", "payload") == "jsonb"
    assert get_setting("keep.me") == {"unicode": "Ọláolúwa ₦", "n": [1, 2.5, None], "nested": {"deep": True}}          # nothing lost, nothing mangled
    assert any("CREATE INDEX gin_tab_notification_delivery_payload" in p for p in done)                                  # the GIN index the DocType asks for is created after the conversion
    assert velora.migrate() == [] and not [p for p in done if "WARNING" in p]                                          # idempotent, and no 'not changed automatically' warning


def test_containment_and_key_filters_find_documents_by_what_is_inside_them(ns):
    d1 = delivery(payload={"event": "New", "actor": "ann", "tags": ["a", "b"], "meta": {"k": 1}})
    d2 = delivery(payload={"event": "Save", "actor": "bob", "tags": ["b"]})
    delivery(payload={"event": "New"})
    delivery()
    q = lambda f: sorted(r["name"] for r in get_list("Notification Delivery", filters=[f], fields=["name"], ignore_permissions=True))  # noqa: E731
    if not on_pg():
        with pytest.raises(ValidationError, match="needs PostgreSQL"):
            q(["payload", "json_contains", {"event": "New"}])
        return
    assert len(q(["payload", "json_contains", {"event": "New"}])) == 2
    assert q(["payload", "json_contains", {"event": "New", "actor": "ann"}]) == [d1.name]
    assert q(["payload", "json_contains", {"tags": ["b"]}]) == sorted([d1.name, d2.name])                              # arrays: contains this element
    assert q(["payload", "json_contains", {"meta": {"k": 1}}]) == [d1.name]                                            # nested structures
    assert q(["payload", "json_contains", {"event": "Nope"}]) == [] and q(["payload", "json_has_key", "actor"]) == sorted([d1.name, d2.name])
    assert q(["payload", "json_has_key", "nothing"]) == []
    with pytest.raises(ValidationError, match="only applies to JSON fields"):
        q(["subject", "json_contains", {"a": 1}])
    with pytest.raises(ValidationError, match="needs a key name"):
        q(["payload", "json_has_key", 5])


def test_the_gin_index_exists_and_the_planner_uses_it(ns):
    if not on_pg():
        pytest.skip("PostgreSQL only")
    for i in range(300):
        delivery(payload={"event": "New" if i % 50 else "Rare", "n": i})
    with get_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.exec_driver_sql("ANALYZE tab_notification_delivery")
    idx = raw("select indexdef from pg_indexes where indexname = 'gin_tab_notification_delivery_payload'")
    assert idx and "USING gin" in idx[0][0] and "jsonb_path_ops" in idx[0][0]
    with db.transaction() as c:
        c.exec_driver_sql("SET LOCAL enable_seqscan = off")
        plan = "\n".join(r[0] for r in c.execute(text("""EXPLAIN SELECT name FROM tab_notification_delivery WHERE payload::jsonb @> '{"event": "Rare"}'::jsonb""")).all())
    assert "gin_tab_notification_delivery_payload" in plan


def test_jsonb_normalises_so_exact_text_must_never_be_kept_in_it(ns):
    """Documents the trade-off: key order and duplicate keys are not preserved. A signed webhook body must be stored as TEXT."""
    if not on_pg():
        pytest.skip("PostgreSQL only")
    with db.transaction() as c:
        out = c.exec_driver_sql("""select '{"b":1, "a":2, "a":3}'::jsonb::text, '{"b":1, "a":2, "a":3}'::json::text""").one()
    assert out[0] == '{"a": 3, "b": 1}' and out[1] == '{"b":1, "a":2, "a":3}'


def test_a_json_index_option_is_accepted_only_where_it_makes_sense(ns):
    from velora.meta.registry import registry
    f = next(f for f in registry.get("Notification Delivery").fields if f.fieldname == "payload")
    assert f.json_index is True and not any(getattr(x, "json_index", False) for x in registry.get("Notification Log").fields)
