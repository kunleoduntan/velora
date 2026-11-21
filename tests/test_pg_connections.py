"""PostgreSQL connection usage is visible (pg status, doctor), and a shortage is explained before it becomes 'remaining connection slots are reserved for roles with the SUPERUSER attribute'."""
import pytest

from velora import db, pg


# ============================== the arithmetic (no database needed) ==============================
ROWS = [("velora_cp", "velora_cp", "idle", 7), ("velora_acme", "velora_acme", "idle", 4), ("app_x", "x", "active", 1)]


def test_the_summary_counts_usable_slots_without_the_ones_kept_for_superusers():
    s = pg.summarize_connections(ROWS, max_connections=100, reserved=3)
    assert s["in_use"] == 12 and s["usable"] == 97 and s["max"] == 100 and s["reserved_for_superusers"] == 3 and s["percent"] == 12
    assert [t["role"] for t in s["top"]][:2] == ["velora_cp", "velora_acme"]                                          # biggest holders first


def test_the_summary_shows_at_most_six_holders_and_survives_empty_and_tiny_limits():
    many = [(f"r{i}", "d", "idle", i + 1) for i in range(20)]
    assert len(pg.summarize_connections(many, 100, 3)["top"]) == 6 and pg.summarize_connections(many, 100, 3)["top"][0]["connections"] == 20
    assert pg.summarize_connections([], 100, 3)["percent"] == 0
    assert pg.summarize_connections([("a", "b", "idle", 1)], 3, 3)["usable"] == 1                                    # never divides by zero


@pytest.mark.parametrize("in_use,expect", [(0, None), (66, None), (67, None), (68, "warn"), (96, "warn"), (97, "out"), (140, "out")])      # of 97 usable: 67 = 69%, 68 = 70%
def test_advice_starts_at_70_percent_and_says_so_plainly_when_the_server_is_out(in_use, expect):
    info = pg.summarize_connections([("r", "d", "idle", in_use)], max_connections=100, reserved=3)
    note = pg.connection_advice(info)
    if expect is None:
        assert note is None
    elif expect == "warn":
        assert note and "usable PostgreSQL connections are in use" in note and "pgbouncer" in note and "OUT" not in note
    else:
        assert note and "OUT of connections" in note and "refused" in note


def test_the_threshold_is_where_the_documentation_says():
    assert pg.WARN_CONNECTIONS == 70


# ============================== against a real PostgreSQL ==============================
def test_status_reports_real_usage_and_it_moves_when_connections_are_opened(site):
    with db.transaction() as c:
        if not pg.is_pg(c):
            pytest.skip("PostgreSQL only")
        before = pg.status(c)["connections"]
        assert before["in_use"] >= 1 and before["max"] >= before["usable"] >= 1 and 0 <= before["percent"] <= 100
        assert before["top"] and all({"role", "database", "state", "connections"} <= set(t) for t in before["top"])
    held = [db.get_engine().raw_connection() for _ in range(6)]                                                      # six more connections, held open
    try:
        with db.transaction() as c:
            after = pg.status(c)["connections"]["in_use"]
        assert after >= before["in_use"] + 5
    finally:
        for h in held:
            h.close()


def test_a_nearly_full_server_puts_the_warning_first_in_the_advice(site, monkeypatch):
    with db.transaction() as c:
        if not pg.is_pg(c):
            pytest.skip("PostgreSQL only")
        monkeypatch.setattr(pg, "connections", lambda conn: pg.summarize_connections([("velora", "d", "idle", 90)], 100, 3))
        st = pg.status(c)
    assert st["advice"][0].startswith("90 of 97 usable PostgreSQL connections are in use (93%)")
    assert st["connections"]["percent"] == 93
