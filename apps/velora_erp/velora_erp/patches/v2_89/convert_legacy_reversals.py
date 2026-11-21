"""Upgrade: posting reversals are gone; a wrong document is cancelled and the posting is deleted (like ERPNext).

Earlier releases undid a posting by adding a second, opposite batch (event "Reversal"). For every such pair:

* the automatic reversal of an Accrual is a real accounting entry, so it stays; it becomes an ordinary "Adjustment" posting;
* every other pair (a reversed Receipt, Payment, Investment ... ) nets to nothing, so both batches and their ledger rows are deleted and
  the document they belonged to is marked Cancelled, with a Posting Cancellation Log note.

Safe to run again; a database that never reversed anything is not touched."""
from datetime import datetime, timezone

from sqlalchemy import inspect, text

from velora import db, new_doc
from velora.db.tables import table_name


def _has(conn, table, column):
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def execute():
    batch_t, line_t, ledger_t = table_name("Financial Posting Batch"), table_name("Financial Posting Line"), table_name("Account Ledger Record")
    done = []
    with db.transaction() as conn:
        if not _has(conn, batch_t, "reversal_of"):
            return
        pairs = conn.execute(text(f'SELECT name, reversal_of FROM "{batch_t}" WHERE posting_event = \'Reversal\'')).all()
        for rev, orig in pairs:
            src = conn.execute(text(f'SELECT source_doctype, source_name, posting_date FROM "{batch_t}" WHERE name = :n'), {"n": orig}).first()
            if src and src[0] == "Accrual":
                conn.execute(text(f'UPDATE "{batch_t}" SET posting_event = \'Adjustment\', reversal_of = NULL, source_doctype = :d, source_name = :s WHERE name = :n'),
                             {"n": rev, "d": src[0], "s": src[1]})
                if _has(conn, ledger_t, "reversal_of"):
                    conn.execute(text(f'UPDATE "{ledger_t}" SET reversal_of = NULL WHERE posting_batch = :n'), {"n": rev})
                continue
            rows = conn.execute(text(f'SELECT COUNT(*) FROM "{ledger_t}" WHERE posting_batch IN (:a, :b)'), {"a": orig, "b": rev}).scalar() or 0
            for b in (orig, rev):
                conn.execute(text(f'DELETE FROM "{ledger_t}" WHERE posting_batch = :b'), {"b": b})
                conn.execute(text(f'DELETE FROM "{line_t}" WHERE parent = :b'), {"b": b})
                conn.execute(text(f'DELETE FROM "{batch_t}" WHERE name = :b'), {"b": b})
            if src and src[0] != "Financial Posting Batch":
                try:
                    tname = table_name(src[0])
                    conn.execute(text(f'UPDATE "{tname}" SET docstatus = 2 WHERE name = :n'), {"n": src[1]})
                    if _has(conn, tname, "status"):
                        conn.execute(text(f'UPDATE "{tname}" SET status = \'Cancelled\' WHERE name = :n'), {"n": src[1]})
                except Exception:
                    pass
                done.append((src[0], src[1], src[2], rows))
    for doctype, name, posting_date, rows in done:
        log = new_doc("Posting Cancellation Log", source_doctype=doctype, source_name=name, posting_date=posting_date, cancelled_by="Upgrade",
                      cancelled_on=datetime.now(timezone.utc).replace(tzinfo=None), reason="Reversed before posting reversals were removed",
                      ledger_rows_removed=rows, unlinked=["The posting and its reversal were deleted; they netted to nothing."], snapshot={})
        log.flags.trusted_source = True
        log.insert(ignore_permissions=True)
