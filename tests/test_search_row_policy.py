"""Global search must not leak the titles of records a row-level policy hides."""
import pytest
from fastapi.testclient import TestClient

from velora import new_doc
from velora.api import create_app
from velora.permissions import Session, session_as
from velora_search import indexer

from test_row_security_v038 import _setup_role
from test_search import sx  # noqa: F401  (a database with the demo and search apps)

SCOPED = frozenset({"Sales Scoped"})


def mine(user, *names):
    with session_as(Session(user, SCOPED)):
        return [new_doc("Customer", customer_name=n).insert().name for n in names]


def titles(hits):
    return [h["title"] for h in hits]


def test_a_row_restricted_user_finds_only_their_own_records(sx):
    _setup_role()
    alice, = mine("alice@example.com", "Zanzibar Alice Stores")
    mine("bob@example.com", "Zanzibar Bob Stores")
    with session_as(Session("alice@example.com", SCOPED)):
        hits = indexer.query("zanzibar")
    assert [h["name"] for h in hits] == [alice] and titles(hits) == ["Zanzibar Alice Stores"]                 # Bob's title is not even visible
    with session_as(Session("bob@example.com", SCOPED)):
        assert titles(indexer.query("zanzibar")) == ["Zanzibar Bob Stores"]
    with session_as(Session("lead@example.com", frozenset({"System Manager"}))):
        assert sorted(titles(indexer.query("zanzibar"))) == ["Zanzibar Alice Stores", "Zanzibar Bob Stores"]   # someone with no policy sees both


def test_records_outside_the_scope_that_rank_first_cannot_crowd_out_the_ones_you_may_see(sx):
    _setup_role()
    mine("bob@example.com", *[f"Zanzibar A{i:02d} Trading" for i in range(30)])                                # 30 out-of-scope matches that sort BEFORE mine
    (own,) = mine("alice@example.com", "Zanzibar Zzz Trading")
    with session_as(Session("alice@example.com", SCOPED)):
        assert [h["name"] for h in indexer.query("zanzibar", limit=3)] == [own]                              # a plain "fetch 3 then filter" would return nothing


def test_the_limit_is_honoured_and_pages_are_not_repeated(sx):
    _setup_role()
    names = mine("alice@example.com", *[f"Zanzibar Mine {i:03d}" for i in range(60)])
    mine("bob@example.com", *[f"Zanzibar Theirs {i:03d}" for i in range(60)])
    with session_as(Session("alice@example.com", SCOPED)):
        hits = indexer.query("zanzibar", limit=50)
    assert len(hits) == 50 and len({h["name"] for h in hits}) == 50 and {h["name"] for h in hits} <= set(names)


def test_an_unrestricted_search_is_unchanged(sx):
    with session_as(Session("boss@example.com", frozenset({"System Manager"}))):
        new_doc("Customer", customer_name="Zanzibar One").insert()
        assert titles(indexer.query("zanzibar")) == ["Zanzibar One"]


def test_the_search_api_applies_the_same_scope(sx):
    _setup_role()
    mine("alice@example.com", "Zanzibar Alice Stores")
    mine("bob@example.com", "Zanzibar Bob Stores")
    c = TestClient(create_app(auto_init=False))
    r = c.get("/api/search?q=zanzibar", headers={"X-Velora-User": "alice@example.com", "X-Velora-Roles": "Sales Scoped"})
    assert r.status_code == 200 and titles(r.json()["data"]) == ["Zanzibar Alice Stores"]
