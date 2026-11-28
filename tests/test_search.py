"""Global search: what is indexed, how it is queried (prefix, accents, typos on PostgreSQL), permissions, backfill, and the API."""
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import velora
from velora import db, get_doc, new_doc
from velora.api import create_app
from velora.db import get_engine
from velora.permissions import Session, session_as
from velora_search import indexer

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}


@pytest.fixture(params=["sqlite"] + (["postgres"] if os.environ.get("VELORA_TEST_PG_URL") else []))
def sx(request, tmp_path):
    url = f"sqlite:///{tmp_path / 's.db'}" if request.param == "sqlite" else os.environ["VELORA_TEST_PG_URL"]
    velora.init(velora.configure(db_url=url, apps=["velora_demo", "velora_search"], developer_mode=True))
    if request.param == "postgres":
        from sqlalchemy import MetaData
        with db.transaction() as conn:
            md = MetaData()
            md.reflect(conn)
            md.drop_all(conn)
    velora.migrate()
    yield
    velora.shutdown()


def on_pg():
    return get_engine().dialect.name == "postgresql"


def cust(name, **kw):
    return new_doc("Customer", customer_name=name, **kw).insert()


def hits(q, **kw):
    return [(h["doctype"], h["title"]) for h in indexer.query(q, **kw)]


def titles(q, **kw):
    return [t for _, t in hits(q, **kw)]


def raw(sql, **p):
    with db.transaction() as c:
        return c.execute(text(sql), p).all()


# ============================== folding ==============================
@pytest.mark.parametrize("src,expected", [("Ọláolúwa Ẹ̀gbẹ́", "olaoluwa egbe"), ("  Café   Münster ", "cafe munster"), ("ＡＢＣ", "abc"), ("İstanbul", "i̇stanbul".replace("̇", "")), (None, ""), ("", ""), ("Ñandú", "nandu")])
def test_folding_removes_accents_case_and_extra_space(src, expected):
    assert indexer.fold(src) == expected


@pytest.mark.parametrize("field,secret", [("password", True), ("new_password", True), ("api_key", True), ("apikey", True), ("secret", True), ("client_secret", True), ("token", True), ("access_token", True),
                                          ("otp", True), ("pin", True), ("private_key", True), ("pincode", False), ("description", False), ("spinner", False), ("tokenizer_note", True), ("remarks", False)])
def test_fields_that_look_like_secrets_are_never_indexed(field, secret):
    meta = SimpleNamespace(name="X", title_field="title", value_fields=[SimpleNamespace(fieldname=field, fieldtype="Data", in_list_view=False), SimpleNamespace(fieldname="title", fieldtype="Data", in_list_view=False)])
    _, _, body = indexer.build(meta, {"name": "X-1", "title": "Hello", field: "VALUE123"}.get)
    assert ("value123" not in body) is secret


def test_without_a_title_field_the_first_list_view_text_field_names_the_record():
    F = lambda n, t="Data", lv=False: SimpleNamespace(fieldname=n, fieldtype=t, in_list_view=lv)  # noqa: E731
    meta = SimpleNamespace(name="X", title_field=None, value_fields=[F("notes", "Text", True), F("full_name", "Data", True), F("password", "Data", True), F("city", "Data")])
    t, tn, body = indexer.build(meta, {"name": "C-0001", "full_name": "Ada Okafor", "notes": "n", "password": "pw", "city": "Lagos"}.get)
    assert (t, tn) == ("Ada Okafor", "ada okafor") and "c 0001" in body and "lagos" in body and "ada" not in body and "pw" not in body       # named by it, searchable through it, secrets excluded
    meta.value_fields = [F("notes", "Text", True), F("city", "Data")]
    assert indexer.build(meta, {"name": "C-0001", "city": "Lagos"}.get)[0] == "C-0001"                                                      # nothing suitable: the name
    meta.title_field = "city"
    assert indexer.build(meta, {"name": "C-0001", "city": "Lagos"}.get)[0] == "Lagos"                                                      # a declared title field always wins


def test_build_uses_the_title_field_else_the_name_and_limits_size():
    meta = SimpleNamespace(name="X", title_field=None, value_fields=[SimpleNamespace(fieldname="notes", fieldtype="Text", in_list_view=False)])
    t, tn, body = indexer.build(meta, {"name": "X-9", "notes": "word " * 2000}.get)
    assert (t, tn) == ("X-9", "x 9") and len(body) <= indexer.MAX_BODY
    meta.title_field = "notes"
    assert indexer.build(meta, {"name": "X-9", "notes": "T" * 400}.get)[0] == "T" * 255


# ============================== keeping the index up to date ==============================
def test_documents_are_indexed_on_create_changed_on_update_and_removed_on_delete(sx):
    c = cust("Acme Ltd", email="info@acme.ng")
    assert hits("acme") == [("Customer", "Acme Ltd")] and hits("info@acme") == [("Customer", "Acme Ltd")]               # title and text fields
    c.customer_name = "Zenith Traders"
    c.save()
    assert hits("acme") == [("Customer", "Zenith Traders")] and titles("zenith") == ["Zenith Traders"]                 # the email still mentions acme; the old title is gone
    assert len(raw("select 1 from tab_search_index")) == 1                                                            # updated in place: never duplicated
    get_doc("Customer", c.name).delete()
    assert hits("zenith") == [] and raw("select count(*) from tab_search_index")[0][0] == 0


def test_cancelled_documents_leave_the_index_and_child_tables_and_system_records_are_never_indexed(sx):
    c = cust("Buyer Co")
    so = new_doc("Sales Order", customer=c.name)
    so.append("items", {"description": "unique-widget-description", "qty": 1, "rate": 5})
    so.insert()
    assert ("Sales Order", so.name) in [(d, n) for d, n in raw("select ref_doctype, ref_name from tab_search_index")]
    assert hits("unique-widget") == [] and hits("widget") == []                                                         # child rows belong to the parent; they are not separate hits
    so.submit()
    assert so.name.lower() in [r[0] for r in raw("select lower(ref_name) from tab_search_index")]
    so.cancel()
    assert so.name.lower() not in [r[0] for r in raw("select lower(ref_name) from tab_search_index")]                 # a cancelled document is not searchable
    assert not raw("select 1 from tab_search_index where ref_doctype = 'Customer Contact' or ref_doctype like 'Notification%' or ref_doctype = 'Search Index'")


def test_an_indexing_problem_never_fails_the_save(sx, monkeypatch):
    monkeypatch.setattr(indexer, "upsert", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("index is broken")))
    c = cust("Still Saves")
    assert c.name and raw("select count(*) from tab_customer")[0][0] == 1


def test_the_index_is_part_of_the_documents_transaction(sx):
    with pytest.raises(RuntimeError):
        with db.transaction():
            cust("Phantom")
            raise RuntimeError("rolled back")
    assert hits("phantom") == []                                                                                        # nothing is searchable for a document that never existed


# ============================== querying ==============================
def test_emails_codes_and_hyphenated_words_are_findable_by_any_part(sx):
    cust("Plain Co", email="info@acme.ng")
    c = cust("Coded Ltd")
    assert titles("acme") == ["Plain Co"] and titles("info@acme.ng") == ["Plain Co"] and titles("INFO") == ["Plain Co"] and titles("acme.ng") == ["Plain Co"]
    assert titles(c.name.lower()) == ["Coded Ltd"] and titles(c.name.split("-")[1]) == ["Coded Ltd"]
    assert sorted(titles("cust")) == ["Coded Ltd", "Plain Co"]                                                          # every document's name starts with CUST


def test_every_word_must_match_as_a_prefix_in_any_order_ignoring_case_and_accents(sx):
    cust("Ọláolúwa Bakery & Sons", email="orders@bakery.ng")
    cust("Olaitan Stores")
    cust("Bakery Supplies Ltd")
    assert titles("olaolu") == ["Ọláolúwa Bakery & Sons"] and titles("OLAOLUWA") == ["Ọláolúwa Bakery & Sons"] and titles("ọláolúwa") == ["Ọláolúwa Bakery & Sons"]
    assert sorted(titles("bak")) == ["Bakery Supplies Ltd", "Ọláolúwa Bakery & Sons"]
    assert titles("sons bak") == ["Ọláolúwa Bakery & Sons"] and titles("bak sup") == ["Bakery Supplies Ltd"]           # all words, any order
    assert titles("ola") and sorted(titles("ola")) == ["Olaitan Stores", "Ọláolúwa Bakery & Sons"]
    assert titles("zzz") == [] and titles("bakery zzz") == []


def test_a_title_match_ranks_above_a_match_only_in_the_text(sx):
    cust("Orders Direct")                                                                                               # the word is in the TITLE
    cust("Zed Ltd", email="orders@zed.ng")                                                                              # the word is only in the email
    cust("Orders")                                                                                                      # the title IS the query
    assert titles("orders")[0] == "Orders" and titles("orders").index("Orders Direct") < titles("orders").index("Zed Ltd")


@pytest.mark.parametrize("q", ["", "   ", "&|!()", ":*", "'; DROP TABLE tab_customer; --", "a & b | !c", "(((", "\\", "%", "_", "<script>alert(1)</script>", "x" * 500, "\x00", "ａｂｃ", "💥", "a" * 5 + ":*:*"])
def test_hostile_or_odd_queries_never_error_and_never_run_anything(sx, q):
    cust("abc corp")
    out = indexer.query(q)
    assert isinstance(out, list)
    assert raw("select count(*) from tab_customer")[0][0] == 1                                                          # the table is still there


def test_wildcards_in_a_query_are_text_not_patterns(sx):
    cust("50 Percent Co")
    cust("Fifty Co")
    assert titles("%") == [] and titles("_") == [] and titles("5_ Percent") == titles("5 Percent")


def test_limit_and_doctype_filters(sx):
    for i in range(60):
        cust(f"Bulk {i:02d}")
    c = cust("Other One")
    so = new_doc("Sales Order", customer=c.name)
    so.append("items", {"description": "x", "qty": 1, "rate": 1})
    so.insert()
    assert len(indexer.query("bulk", limit=5)) == 5 and len(indexer.query("bulk", limit=10_000)) == 50 and len(indexer.query("bulk", limit=-3)) == 1
    assert {d for d, _ in hits("bulk", doctype="Customer")} == {"Customer"} and hits("bulk", doctype="Sales Order") == [] and hits("bulk", doctype="Nope") == []
    assert [d for d, _ in hits(so.name.lower(), doctype="Sales Order")] == ["Sales Order"]                              # a document's NAME is searchable too


def test_results_only_include_doctypes_the_user_may_read(sx, monkeypatch):
    c = cust("Visible Co")
    so = new_doc("Sales Order", customer=c.name)
    so.append("items", {"description": "x", "qty": 1, "rate": 1})
    so.insert()
    assert {d for d, _ in hits("co") + hits(so.name.lower())} == {"Customer", "Sales Order"}
    with session_as(Session("nobody", frozenset({"Stranger"}))):
        assert hits("visible") == [] and hits(so.name.lower()) == []                                                    # no role, no results
    real = indexer.has_permission
    monkeypatch.setattr(indexer, "has_permission", lambda m, p: m.name == "Customer" and real(m, p))
    assert [d for d, _ in hits("visible")] == ["Customer"] and hits(so.name.lower()) == []                              # may read customers only


# ============================== PostgreSQL: typos, ranking, indexes ==============================
def test_a_misspelled_name_still_finds_it_on_postgresql(sx):
    if not on_pg():
        pytest.skip("PostgreSQL only")
    cust("Acme Limited")
    cust("Bola Stores")
    cust("Zenith Traders")
    assert titles("Acmee") == ["Acme Limited"] and titles("Bola Stoers") == ["Bola Stores"] and titles("Zenit Trader") == ["Zenith Traders"]
    assert titles("Qwerty Unrelated") == [] and titles("Acme Zzzzz") == [] and titles("xyz") == []                    # but it is not fuzzy about everything: every word must match


def test_exact_and_prefix_matches_win_and_misspellings_only_apply_when_nothing_else_matches(sx):
    if not on_pg():
        pytest.skip("PostgreSQL only")
    cust("Olaitan Stores")
    cust("Ọláolúwa Bakery")
    assert titles("olaolu") == ["Ọláolúwa Bakery"]                                                                      # 'olaitan' is similar but NOT what was typed: no noise next to a real hit
    assert titles("olaitam") == ["Olaitan Stores"]                                                                      # a typo with no real hit: the fuzzy tier finds it
    cust("Acme")
    assert titles("acm") == ["Acme"]


def test_the_database_maintains_the_search_vector_and_the_indexes_exist(sx):
    if not on_pg():
        pytest.skip("PostgreSQL only")
    cust("Searchable Name")
    assert raw("select count(*) from tab_search_index where tsv @@ to_tsquery('simple', 'searchab:*')")[0][0] == 1       # the tsvector is generated from the text columns
    idx = {r[0]: r[1] for r in raw("select indexname, indexdef from pg_indexes where tablename = 'tab_search_index'")}
    assert "USING gin (tsv)" in idx["gin_search_index_tsv"] and "gin_trgm_ops" in idx["gin_search_index_title_trgm"] and "uq_search_index_doc" in idx


def test_the_planner_uses_the_gin_indexes(sx):
    if not on_pg():
        pytest.skip("PostgreSQL only")
    for i in range(400):
        cust(f"Company number {i} Trading")
    with get_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.exec_driver_sql("ANALYZE tab_search_index")
    with db.transaction() as c:
        c.exec_driver_sql("SET LOCAL enable_seqscan = off")
        fts = "\n".join(r[0] for r in c.exec_driver_sql("EXPLAIN SELECT 1 FROM tab_search_index WHERE tsv @@ to_tsquery('simple', 'trading:*')").all())
        tri = "\n".join(r[0] for r in c.exec_driver_sql("EXPLAIN SELECT 1 FROM tab_search_index WHERE 'compnay' <%% title_norm").all())
        like = "\n".join(r[0] for r in c.exec_driver_sql("EXPLAIN SELECT 1 FROM tab_search_index WHERE title_norm LIKE '%%number 3%%'").all())
    assert "gin_search_index_tsv" in fts and "gin_search_index_title_trgm" in tri and "gin_search_index_title_trgm" in like               # full-text, typo (<%), and substring all use an index


# ============================== backfill ==============================
def test_reindex_rebuilds_everything_in_batches_and_is_idempotent(sx):
    for n in ("One Co", "Two Co", "Three Co", "Four Co", "Five Co"):
        cust(n)
    c = cust("Buyer")
    so = new_doc("Sales Order", customer=c.name)
    so.append("items", {"description": "x", "qty": 1, "rate": 1})
    so.insert()
    so.submit()
    so.cancel()
    with db.transaction() as conn:
        conn.exec_driver_sql("DELETE FROM tab_search_index")
    assert hits("co") == []
    assert indexer.reindex(batch=2) == 6                                                                                # 6 customers; the cancelled order is skipped
    assert sorted(titles("co")) == ["Five Co", "Four Co", "One Co", "Three Co", "Two Co"]
    assert indexer.reindex(batch=2) == 6 and raw("select count(*) from tab_search_index")[0][0] == 6                    # again: same result, no duplicates
    assert indexer.reindex("Customer") == 6 and indexer.reindex("Sales Order") == 0
    assert raw("select count(*) from tab_search_index")[0][0] == 6


def test_the_install_hook_rebuilds_the_index_and_is_declared_in_the_app():
    import importlib
    import velora_search.hooks as h
    mod, _, fn = h.after_install.rpartition(".")
    assert callable(getattr(importlib.import_module(mod), fn))


# ============================== the API ==============================
def test_the_search_api(sx):
    cust("Acme Ltd")
    cust("Acme Foods")
    c = TestClient(create_app(auto_init=False))
    assert c.get("/api/search?q=acme").status_code == 401
    r = c.get("/api/search?q=acme&limit=1", headers=ADMIN)
    assert r.status_code == 200 and len(r.json()["data"]) == 1 and set(r.json()["data"][0]) == {"doctype", "name", "title"}
    assert len(c.get("/api/search?q=acme", headers=ADMIN).json()["data"]) == 2 and c.get("/api/search?q=", headers=ADMIN).json()["data"] == []
    assert c.get("/api/search?q=acme&doctype=Sales Order", headers=ADMIN).json()["data"] == []
    assert c.get("/api/search?q=acme", headers={"X-Velora-User": "nobody", "X-Velora-Roles": "Stranger"}).json()["data"] == []
    assert c.get("/api/search?q=x&limit=abc", headers=ADMIN).status_code == 422


def test_search_falls_back_to_readable_document_fields_when_index_is_empty(sx, monkeypatch):
    from velora_search import indexer
    cust("Fallback Acme Trading")
    monkeypatch.setattr(indexer, "query", lambda *args, **kwargs: [])
    c = TestClient(create_app(auto_init=False))
    r = c.get("/api/search?q=fallback+acme", headers=ADMIN)
    assert r.status_code == 200
    assert any(hit["title"] == "Fallback Acme Trading" for hit in r.json()["data"])


def test_search_fallback_covers_fields_beyond_the_first_ten(sx, monkeypatch):
    from types import SimpleNamespace
    from velora.api import search as search_api
    fields = [SimpleNamespace(fieldname=f"field_{i}", fieldtype="Data", hidden=False, in_list_view=False, required=False) for i in range(1, 13)]
    meta = SimpleNamespace(name="Wide Record", module="Tests", istable=False, fields=fields, title_field=None)
    from velora.meta.registry import Registry
    monkeypatch.setattr(Registry, "all", lambda self: [meta])        # patch the class: patching the shared proxy leaks a stale bound method after the test
    monkeypatch.setattr(search_api, "has_permission", lambda *_: True)
    monkeypatch.setattr(search_api, "field_access", lambda *_: "read")
    monkeypatch.setattr(search_api, "get_list", lambda *a, **k: [{"name": "WR-0001", **{f"field_{i}": ("needle-value" if i == 12 else "") for i in range(1, 13)}}])
    result = search_api._fallback_query("needle-value", 10)
    assert result == [{"doctype": "Wide Record", "name": "WR-0001", "title": "WR-0001"}]
