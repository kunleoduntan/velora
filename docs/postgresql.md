# Using PostgreSQL properly

Velora runs on SQLite (development, tests) and PostgreSQL (production). Everything works on both, and the rules are always enforced in Python. On PostgreSQL the **database enforces them too**, and reports get capabilities SQLite does not have. `velora pg status` shows what is active on your server.

## 1. The database enforces the ledger (`velora_accounts`)
These live inside the database, so not even a raw `UPDATE`, a script or a bug can break them:

| Rule | How |
|---|---|
| **The general ledger is append-only** | triggers refuse every `UPDATE`, `DELETE` and `TRUNCATE` on GL Entry, except flagging an entry cancelled (0 to 1, with nothing else changed, never back): a mistake is corrected by cancelling the document and amending it |
| **Every voucher balances** | a *deferred* constraint trigger checks debits = credits when the transaction **commits** (so a voucher may be built line by line; an unbalanced one can never be committed) |
| **A ledger line is one positive side** | `CHECK (debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0))` (added `NOT VALID`, so old rows are never rejected; every new row is checked) |
| **Fiscal years never overlap** | an **exclusion constraint** on the date range (GiST), so two people creating overlapping years at the same instant cannot both succeed |

Speed structures: a **BRIN** index on the append-only posting date (tiny; ideal for date ranges); a **covering index** `(account, posting_date) INCLUDE (debit, credit, is_cancelled)` so a balance is answered by an *index-only scan*; **partial indexes** over only invoices still owing money. A test uses `EXPLAIN` to prove the planner picks each one.

**A real bug this found:** `ledger.post()` and `ledger.reverse()` committed one line at a time when called outside a document's transaction (a script, a direct call). A crash between two lines would have left half a voucher. They are now atomic however they are called.

Applied automatically by `velora migrate` / `install-app` / `upgrade`; only when the SQL changed (checksum); all-or-nothing with the table changes; skipped (and retried next time) if a required extension cannot be created. Existing data is never rejected by a new constraint.

### For app developers: `pg_objects`
```python
# hooks.py
pg_objects = [{"name": "invoice_no_negative", "requires": ["btree_gist"],         # extensions (optional)
               "sql": ["ALTER TABLE tab_x ADD CONSTRAINT ... NOT VALID"]}]       # a LIST of idempotent statements
```
Allowed extensions: pg_trgm, unaccent, btree_gist, citext, pgcrypto, hstore, tablefunc, pg_stat_statements.

## 2. Reporting
Summary reports (`group_by` + `measures`) gained:

| | |
|---|---|
| `count_distinct` | distinct values of any column (portable) |
| per-measure `where` | `{"fn":"sum","field":"credit_limit","where":[["status","=","Blocked"]]}` becomes `SUM(...) FILTER (WHERE ...)`: several slices of the same rows in one query (portable) |
| `median`, `percentile` (`"p": 90`), `stddev` | PostgreSQL's ordered-set/statistical aggregates (a clear error on SQLite) |
| `"rollup": true` | **true subtotals and grand totals** from `GROUP BY ROLLUP`: the average, median or largest of a group, not a blank. Sums stay live Excel formulas. PostgreSQL |
| `"gap_fill": true` | a time series shows **every** period, zero for empty ones (blank for averages: never invented). Portable. Needs the date as the only `group_by` |

Example: customers by group and status, with real subtotals:
```json
{"type":"summary","ref_doctype":"Customer","group_by":["customer_group","status"],"rollup":true,
 "measures":[{"fn":"count"},{"fn":"sum","field":"credit_limit"},{"fn":"avg","field":"credit_limit"},{"fn":"median","field":"credit_limit"}]}
```
(Wholesale: mean 3,750 but median 2,500, because one customer's 9,000 drags the mean; the grand median is of all 7 customers, not of the group medians.)

**Not yet in the Desk's report builder screen**: these options work in report definitions and the API; the builder UI still offers the original five functions.

## 3. Looking after the server
`velora pg status` (`--json`) shows version, extensions, the database rules applied, the largest tables, and **advice**: no WAL archiving (so no point-in-time recovery), `pg_stat_statements` not loaded, extensions missing, versions near end of life, autovacuum or synchronous_commit switched off. `velora pg optimize` installs the recommended extensions where your role is allowed and refreshes planner statistics. `velora doctor` includes one PostgreSQL line per server.

## What I deliberately did NOT use, and why
* **Replication, PITR, tablespaces, authentication methods, TLS, tuning**: operations, not application code. Velora reports and advises (above); your host or DBA configures them. **Turn on WAL archiving before go-live** (or use pgBackRest/Barman or your provider's PITR): `velora backup` makes consistent dumps, but a dump cannot restore to 14:02 yesterday.
* **Row-level security**: every company already has its own database, which is a stronger boundary. It may be worth adding later for per-user record visibility.
* **Custom types, procedural languages, foreign data wrappers, PostGIS**: no feature needs them yet; PostGIS when an app needs maps.

## 4. JSONB
JSON columns are **JSONB on PostgreSQL** (JSON elsewhere): smaller, faster to read, indexable, queryable. `velora migrate` converts old databases automatically (one table rewrite per JSON column; values are kept), and `velora doctor`/`migrate` report it. Trade-off: PostgreSQL normalises JSONB (key order is not kept, duplicate keys collapse), so **never store a payload whose exact bytes matter** (e.g. a signed webhook body) in it: use a text field.
* Mark a JSON field `"json_index": true` for a GIN index (`jsonb_path_ops`).
* Filters: `["payload", "json_contains", {"event": "New"}]` (objects, nested structures, array elements) and `["payload", "json_has_key", "actor"]`. PostgreSQL only; a clear error elsewhere.

## 5. Live updates (`LISTEN / NOTIFY`)
The notification bell no longer waits for a poll. When a notification commits, `pg_notify` tells the server process; **one listener per database** forwards a tiny `{kind, user}` event to that user's open browser tabs over `GET /api/events` (server-sent events). Events are sent **only if the transaction commits**, never carry content (the browser re-asks the normal API, so normal permissions apply), and a lost connection reconnects and tells clients to resync. Several server processes work together with no broker. On SQLite (development) the same events flow in-process. Limits: at most 5 live connections per user and 2,000 per server.

## 6. Global search
`velora_search` (built in) indexes every document's title and text: `GET /api/search?q=` and the Desk's search box (Ctrl+K). Matching is accent-insensitive ("Ọláolúwa" is found by "olaolu"), every word must match as the start of a word, results list only DocTypes you may read, and secrets (anything named password/token/key...) are never indexed. **On PostgreSQL** it uses a generated `tsvector` with a GIN index, and **a close misspelling of a title is found when nothing else matches** ("Acmee" finds "Acme Limited", "Bola Stoers" finds "Bola Stores") using `pg_trgm`. Exact and prefix matches always win outright, so typos never add noise next to a real hit. A record is named by its DocType's `title_field`, else its first list-view text field, else its name. Typo tolerance applies to the title, not to every word of the body.

## Still not built (and why)
1. **Partition the ledger by year**, only if a company reaches tens of millions of lines (it forces a table rewrite, so not casually).
2. **Route reports to a read replica**, once you run one.
3. **Row-level security**: each company has its own database, which is a stronger boundary.
