# Database connections (PostgreSQL)

Every company has its own database, so every company has its own connection pool. Velora keeps the **worst case** under a budget so one server cannot use up PostgreSQL's connection slots.

| Setting (`config/common.json` → `db_pool`) | Default | Meaning |
|---|---|---|
| `connection_budget` | 48 | Most connections one Velora process may ever hold (minimum 11) |
| `control_pool_size` / `control_max_overflow` | 2 / 3 | Control plane (sign-in, companies) |
| `company_pool_size` / `company_max_overflow` | 3 / 3 | Each open company |
| `pool_timeout` | 10 s | How long a request waits for a free connection |
| `pool_recycle` | 1800 s | Connections are replaced after this |
| `connect_timeout` | 10 s | Waiting for PostgreSQL to accept |

With the defaults, 7 companies can be open at once (5 + 7 × 6 = 47). Less-used companies are closed and reopened on demand.

Each Velora process (the server, `velora worker`, every CLI command) has its own budget. PostgreSQL's default `max_connections` is 100, so leave room: server + worker + CLI + backups.

## When PostgreSQL has no free slots
- The CLI prints one sentence and exits with code 1 (`VELORA_DEBUG=1` shows the full traceback).
- The API answers **503** with `Retry-After: 5` (`DatabaseBusy`), never a 500.
- `velora pg status` and `velora doctor` warn at 70% of usable slots and show who holds them. Every connection is labelled `application_name = velora:<role>:<company>:<pid>`.

To see who is holding connections:

```
sudo -u postgres psql -c "select usename, datname, application_name, state, count(*) from pg_stat_activity where datname is not null group by 1,2,3,4 order by 5 desc;"
```
