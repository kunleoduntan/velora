"""One writer must never freeze the readers (the Desk showed 'Searching...' forever when a background write held the SQLite file)."""
import threading
import time

from sqlalchemy import text

from velora.site import Site


def test_sqlite_uses_wal_and_a_reader_is_not_blocked_by_an_open_write(tmp_path):
    site = Site("t", f"sqlite:///{tmp_path / 'c.db'}")
    eng = site.engine
    with eng.begin() as c:
        c.execute(text("create table t (a integer)"))
        c.execute(text("insert into t values (1)"))
    with eng.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    writer_in = threading.Event(); release = threading.Event(); result = {}

    def write():
        with eng.begin() as c:
            c.execute(text("insert into t values (2)"))        # an open, uncommitted write
            writer_in.set(); release.wait(10)

    th = threading.Thread(target=write); th.start(); assert writer_in.wait(5)
    start = time.monotonic()
    with eng.connect() as c:
        result["n"] = c.execute(text("select count(*) from t")).scalar()
    result["took"] = time.monotonic() - start
    release.set(); th.join()
    assert result["n"] == 1 and result["took"] < 2          # reads the last committed state at once, does not wait for the writer
