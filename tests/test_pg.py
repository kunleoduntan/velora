"""PostgreSQL-specific: the DATABASE enforces the ledger's rules (raw SQL cannot break them), the planner uses the shipped indexes, and `pg status` advises."""
import secrets
from datetime import date

import pytest
from sqlalchemy import insert, text

import velora
from velora import db, pg, pgobjects
from velora.db import get_engine
from velora.db.tables import get_table
from velora.meta.registry import registry

from test_accounts import books, L  # noqa: F401
from velora_accounts import ledger


def on_pg():
    return get_engine().dialect.name == "postgresql"


def require_pg():
    if not on_pg():
        pytest.skip("PostgreSQL only")


def gl_row(voucher, no, account, debit=0, credit=0, d=date(2026, 3, 1)):
    from velora.document.document import now
    t = now()
    return dict(name=secrets.token_hex(8), owner="t", creation=t, modified=t, modified_by="t", docstatus=0, idx=0, posting_date=d, account=account, debit=debit, credit=credit,
                voucher_type=voucher, voucher_no=no, is_reversal=0)


def raw_insert(rows):
    with db.transaction() as conn:
        conn.execute(insert(get_table("GL Entry")), rows)


def stmt(sql, **p):
    """Run a statement that returns no rows (UPDATE ...)."""
    with db.transaction() as conn:
        return conn.execute(text(sql), p).rowcount


def raw(sql, **p):
    with db.transaction() as conn:
        return conn.execute(text(sql), p).all()


# ============================== the objects are applied, recorded and idempotent ==============================
def test_the_objects_are_applied_once_and_migrate_stays_idempotent(books):
    require_pg()
    applied = {r[0] for r in raw("select name from velora_pg_object")}
    assert {"gl_entry_amounts", "gl_entry_append_only", "gl_entry_balanced", "fiscal_year_no_overlap", "gl_entry_indexes", "open_invoice_indexes"} <= applied
    assert velora.migrate() == []                                                                                    # nothing changed: nothing re-applied


def test_a_changed_object_is_re_applied_and_an_unchanged_one_is_not(books, monkeypatch):
    require_pg()
    objs = registry.pg_objects()
    changed = [dict(o) for o in objs]
    changed[0]["sql"] = list(changed[0]["sql"]) + ["SELECT 1"]
    monkeypatch.setattr(registry.__class__, "pg_objects", lambda self: changed, raising=False)
    plan = [p for p in velora.migrate() if "PG OBJECT" in p]
    assert plan == [f"CHANGE PG OBJECT {objs[0]['name']}"]


def test_an_extension_the_server_will_not_install_skips_the_object_and_retries_later(books, monkeypatch):
    require_pg()
    obj = {"name": "needs_ext", "app": "t", "requires": ["unaccent"], "sql": ["SELECT 1"]}
    monkeypatch.setattr(registry.__class__, "pg_objects", lambda self: [obj], raising=False)
    monkeypatch.setattr(pgobjects, "ensure_extension", lambda conn, n: False)
    plan = [p for p in velora.migrate() if "needs_ext" in p]
    assert len(plan) == 1 and plan[0].startswith("SKIPPED PG OBJECT needs_ext: extension unaccent is not available")
    assert raw("select count(*) from velora_pg_object where name = 'needs_ext'")[0][0] == 0                         # not recorded: it will be tried again
    monkeypatch.undo()
    monkeypatch.setattr(registry.__class__, "pg_objects", lambda self: [obj], raising=False)
    assert [p for p in velora.migrate() if "needs_ext" in p] == ["APPLY PG OBJECT needs_ext"]


def test_object_declarations_are_validated():
    with pytest.raises(Exception, match="needs a name and sql"):
        pgobjects.validate([{"name": "x"}])
    with pytest.raises(Exception, match="declared twice"):
        pgobjects.validate([{"name": "x", "sql": ["s"]}, {"name": "x", "sql": ["s"]}])
    with pytest.raises(Exception, match="unknown extension"):
        pgobjects.validate([{"name": "x", "sql": ["s"], "requires": ["not_allowed"]}])
    with pytest.raises(Exception, match="not on the allowed list"):
        pgobjects.ensure_extension(None, "plpython3u")


def test_on_a_database_that_is_not_postgresql_nothing_changes(books):
    if on_pg():
        pytest.skip("SQLite only")
    assert not [p for p in velora.migrate(dry_run=True) if "PG OBJECT" in p]
    with get_engine().connect() as conn:
        assert pg.status(conn)["postgresql"] is False and "not PostgreSQL" in pg.status(conn)["advice"][0]


# ============================== the ledger cannot be tampered with, even by raw SQL ==============================
def post_voucher():
    ledger.post("Test Voucher", "TV-1", date(2026, 3, 1), [L("Rent", debit=100), L("Utilities", credit=100)])


@pytest.mark.parametrize("sql", ["update tab_gl_entry set debit = 999 where voucher_no = 'TV-1' and debit > 0", "delete from tab_gl_entry where voucher_no = 'TV-1'",
                                 "update tab_gl_entry set account = 'Rent'", "truncate tab_gl_entry", "update tab_gl_entry set is_cancelled = 1, debit = debit + 1 where voucher_no = 'TV-1'",
                                 "update tab_gl_entry set is_cancelled = 1, posting_date = '2026-01-01'", "update tab_gl_entry set is_cancelled = 1, remarks = 'sneaky'"])
def test_updates_deletes_and_truncates_of_the_ledger_are_refused_by_the_database(books, sql):
    require_pg()
    post_voucher()
    with pytest.raises(Exception, match="general ledger cannot be edited or deleted"):
        stmt(sql)
    assert ledger.balance("Rent") == 100 and len(raw("select 1 from tab_gl_entry")) == 2                           # nothing changed


def test_the_only_change_an_entry_may_undergo_is_being_flagged_cancelled_once(books):
    require_pg()
    post_voucher()
    assert stmt("update tab_gl_entry set is_cancelled = 1 where voucher_no = 'TV-1'") == 2                                           # the one permitted change
    assert {r[0] for r in raw("select is_cancelled from tab_gl_entry where voucher_no = 'TV-1'")} == {1}
    assert ledger.balance("Rent") == 0                                                                                  # cancelled entries no longer count
    with pytest.raises(Exception, match="cannot be edited or deleted"):
        stmt("update tab_gl_entry set is_cancelled = 0 where voucher_no = 'TV-1'")                                       # and it can never be undone
    with pytest.raises(Exception, match="cannot be edited or deleted"):
        stmt("delete from tab_gl_entry where voucher_no = 'TV-1'")
    assert len(raw("select 1 from tab_gl_entry")) == 2                                                                  # everything is still on record


def test_an_unbalanced_voucher_cannot_be_committed_but_a_balanced_one_can_pass_through_unbalanced_steps(books):
    require_pg()
    with pytest.raises(Exception, match="Voucher Raw Voucher RV-1 is out of balance by 50"):
        raw_insert([gl_row("Raw Voucher", "RV-1", "Rent", debit=100), gl_row("Raw Voucher", "RV-1", "Utilities", credit=50)])
    assert raw("select count(*) from tab_gl_entry")[0][0] == 0                                                        # the whole transaction rolled back
    with db.transaction() as conn:                                                                                    # one line at a time inside ONE transaction: fine, checked at COMMIT
        t = get_table("GL Entry")
        conn.execute(insert(t), [gl_row("Raw Voucher", "RV-2", "Rent", debit=70)])
        conn.execute(insert(t), [gl_row("Raw Voucher", "RV-2", "Utilities", credit=70)])
    assert ledger.balance("Rent") == 70


@pytest.mark.parametrize("debit,credit,frag", [(-5, 0, "ck_gl_entry_amounts"), (0, -5, "ck_gl_entry_amounts"), (5, 5, "ck_gl_entry_amounts")])
def test_a_ledger_line_is_one_positive_side_only(books, debit, credit, frag):
    require_pg()
    with pytest.raises(Exception, match=frag):
        raw_insert([gl_row("Raw Voucher", "RV-3", "Rent", debit=debit, credit=credit)])


def test_fiscal_years_cannot_overlap_even_when_python_is_bypassed(books):
    require_pg()
    from velora.document.document import now
    t = get_table("Fiscal Year")

    def fy(name, a, b):
        n = now()
        return dict(name=name, owner="t", creation=n, modified=n, modified_by="t", docstatus=0, idx=0, year_name=name, start_date=a, end_date=b, is_closed=0)
    with pytest.raises(Exception, match="ex_fiscal_year_no_overlap"):
        with db.transaction() as conn:
            conn.execute(insert(t), [fy("OVERLAP", date(2026, 6, 1), date(2027, 5, 31))])                            # FY2026 already covers 2026
    with db.transaction() as conn:
        conn.execute(insert(t), [fy("NEXT", date(2028, 1, 1), date(2028, 12, 31))])                                  # a gap-free neighbour is fine
    with pytest.raises(Exception, match="ex_fiscal_year_no_overlap"):
        with db.transaction() as conn:
            conn.execute(insert(t), [fy("INSIDE", date(2028, 3, 1), date(2028, 3, 31))])


def test_a_posting_that_fails_midway_leaves_no_half_voucher_even_outside_a_transaction(books, monkeypatch):
    """Regression found by the database rule: ledger.post() used to commit each line on its own when called outside a document's transaction."""
    import velora_accounts.ledger as lg
    real, calls = lg.new_doc, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("disk full on the second line")
        return real(*a, **k)
    monkeypatch.setattr(lg, "new_doc", flaky)
    with pytest.raises(RuntimeError):
        lg.post("Test Voucher", "TV-9", date(2026, 3, 1), [L("Rent", debit=5), L("Utilities", credit=5)])
    assert len(calls) == 2 and raw("select count(*) from tab_gl_entry")[0][0] == 0                                    # the first line was rolled back with the rest
    monkeypatch.setattr(lg, "new_doc", real)
    assert lg.post("Test Voucher", "TV-9", date(2026, 3, 1), [L("Rent", debit=5), L("Utilities", credit=5)]) == 2


def test_reversal_is_atomic_too(books, monkeypatch):
    import velora_accounts.ledger as lg
    post_voucher()
    real, n = lg.new_doc, []

    def flaky(*a, **k):
        n.append(1)
        if len(n) == 2:
            raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(lg, "new_doc", flaky)
    with pytest.raises(RuntimeError):
        lg.reverse("Test Voucher", "TV-1")
    assert raw("select count(*) from tab_gl_entry")[0][0] == 2 and ledger.balance("Rent") == 100                    # no half-reversal
    monkeypatch.setattr(lg, "new_doc", real)
    assert lg.reverse("Test Voucher", "TV-1") == 2 and ledger.balance("Rent") == 0


# ============================== the planner really uses what we ship ==============================
def explain(sql, **settings):
    with db.transaction() as conn:
        for k, v in settings.items():
            conn.exec_driver_sql(f"SET LOCAL {k} = {v}")
        return "\n".join(r[0] for r in conn.execute(text("EXPLAIN " + sql)).all())


def test_balances_are_answered_from_the_covering_index_and_dates_from_brin_and_open_invoices_from_the_partial_index(books):
    require_pg()
    rows = []
    for i in range(8000):                                                                                              # 16,000 lines over a year
        d = date(2026, 1 + i % 12, 1 + i % 27)
        rows += [gl_row("Bulk", f"B-{i}", "Rent" if i % 2 else "Utilities", debit=10, d=d), gl_row("Bulk", f"B-{i}", "Cash in Hand" if i % 3 else "Main Bank Account", credit=10, d=d)]
    raw_insert(rows)
    with get_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as c:                                  # VACUUM cannot run inside a transaction
        c.exec_driver_sql("VACUUM (ANALYZE) tab_gl_entry")
    q = "SELECT sum(debit), sum(credit) FROM tab_gl_entry WHERE account = 'Rent' AND posting_date <= '2026-06-30' AND COALESCE(is_cancelled, 0) = 0"
    assert "Index Only Scan" in explain(q) and "ix_gl_entry_live_cover" in explain(q)                                   # no table access: the balance comes from the index alone
    r = explain("SELECT account FROM tab_gl_entry WHERE posting_date BETWEEN '2026-03-01' AND '2026-03-31'", enable_seqscan="off", enable_indexscan="off")
    assert "brin_gl_entry_posting_date" in r                                                                           # a date range is a tiny BRIN scan on an append-only table
    inv = explain("SELECT name FROM tab_sales_invoice WHERE customer = 'x' AND docstatus = 1 AND outstanding > 0", enable_seqscan="off")
    assert "ix_sales_invoice_open" in inv
    brin, btree = raw("select pg_relation_size('brin_gl_entry_posting_date'), pg_relation_size('ix_gl_entry_live_cover')")[0]
    assert brin * 10 < btree                                                                                           # the BRIN index is a tiny fraction of a btree over the same table


# ============================== status and advice ==============================
def test_pg_status_reports_the_server_and_gives_actionable_advice(books):
    require_pg()
    with get_engine().connect() as conn:
        s = pg.status(conn)
    assert s["postgresql"] and int(s["version"].split(".")[0]) >= 14 and "btree_gist" in s["extensions"]["installed"]
    assert {"gl_entry_balanced", "fiscal_year_no_overlap"} <= set(s["objects"]["applied"]) and s["objects"]["pending"] == []
    assert s["largest_tables"] and all({"table", "size", "rows_estimate"} <= set(t) for t in s["largest_tables"])
    assert s["settings"]["archive_mode"] in ("off", "on", "always")
    if s["settings"]["archive_mode"] == "off":
        assert any("WAL archiving is OFF" in a and "point in time" in a for a in s["advice"])
    pg_old = pg._major("13.16 (Ubuntu)")
    assert pg_old == 13 and pg._major("16.15") == 16 and pg._major("x") == 0


def test_pg_optimize_installs_the_allowed_extensions_and_analyzes(books):
    require_pg()
    with get_engine().connect() as conn:
        out = pg.optimize(conn)
        conn.commit()
    assert out["postgresql"] and out["analyzed"] and set(out["extensions"]) == {"pg_trgm", "unaccent", "btree_gist"} and out["extensions"]["btree_gist"] is True


# ============================== the command line ==============================
def test_the_pg_commands_on_postgresql_and_on_anything_else(books, capsys, monkeypatch):
    from velora.cli import main
    url = str(get_engine().url.render_as_string(hide_password=False))
    monkeypatch.setenv("VELORA_DB_URL", url)
    monkeypatch.setenv("VELORA_APPS", "velora_accounts")
    assert main(["pg", "status"]) in (0, None)
    out = capsys.readouterr().out
    if not on_pg():
        assert "not PostgreSQL" in out
        assert main(["pg", "optimize"]) in (0, None) and "Not PostgreSQL" in capsys.readouterr().out
        return
    assert "PostgreSQL 1" in out and "Database rules applied: 6" in out and "gl_entry_balanced" in out
    assert main(["pg", "status", "--json"]) in (0, None)
    import json
    j = json.loads(capsys.readouterr().out)
    assert j["postgresql"] and j["objects"]["pending"] == [] and j["advice"] is not None
    assert main(["pg", "optimize"]) in (0, None)
    assert "btree_gist ready" in capsys.readouterr().out
