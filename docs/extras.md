# Optional Python packages (`velora[...]`)

A plain `pip install velora` stays small and always installs. Heavier capabilities are **extras** you add when you need them:

```bash
pip install "velora[all]"            # everything below (except Oracle)
pip install "velora[pdf,data]"       # or pick
velora deps list                     # what is installed, what each extra gives
velora deps install pdf data ml      # same as pip, into the current environment
```

| Extra | Packages | For |
|---|---|---|
| `postgres` | psycopg | PostgreSQL (recommended for real use) |
| `data` | numpy, pandas, python-dateutil, pytz | analysis, reports, time zones |
| `pdf` | reportlab, qrcode[pil], pillow | PDF documents, QR codes, images |
| `ml` | scikit-learn, statsmodels (+ numpy, pandas) | machine learning, statistics |
| `forecast` | prophet, statsmodels, pandas | time-series forecasting (heavy: needs a Stan toolchain) |
| `markets` | yfinance | market data (unofficial Yahoo endpoints: don't depend on it for anything critical) |
| `sftp` | paramiko | SFTP/SSH (bank files, remote servers) |
| `security` | bcrypt | verifying legacy password hashes |

**Why not install all of it by default?** numpy, pandas and scikit-learn are hundreds of MB; Prophet needs Stan; most businesses need none of them; and one failing build would stop the whole framework from installing. XlsxWriter is already part of the core.

**Not `sklearn`:** the `sklearn` package on PyPI is a deliberately broken placeholder. The real package is `scikit-learn` (the `ml` extra); `velora deps install sklearn` tells you so.

**Servers:** `install.sh --extras pdf,data`. **If pip says "externally-managed-environment"**, you are using an OS-managed Python: use a virtual environment (the installer does) instead of `--break-system-packages`.

## For app developers
```python
from velora.optional import require
require("reportlab", "qrcode", feature="Printing invoices")   # one clear message with the exact command if missing
```
Declare what your app needs in `hooks.py`: `required_packages = ["numpy>=1.26", "scikit-learn>=1.4"]`. `velora install-app` and `velora upgrade` **refuse, before touching any database**, if they are missing or too old, and say `velora deps install --app <app>`; `velora update` installs the declared packages of the apps it pulls; `velora doctor` and `velora deps check` report them.

`velora[all]` was verified to **resolve** together (pip dry-run in a clean virtualenv). That proves the versions are compatible; it does not prove Prophet's Stan model compiles on your server.

## The worker and scheduler
`velora worker` runs scheduled tasks for every company (delivering notifications, escalation, date reminders). Apps register tasks in `hooks.py`:
```python
scheduler_events = {"every_tick": ["myapp.jobs.drain"], "every_minute": [...], "hourly": [...], "daily": [...]}
```
Each frequency is claimed with one atomic UPDATE, so you can run several workers; a failing task never stops the others; companies whose database needs an upgrade (or during maintenance mode) are skipped. Run it as a service next to the web server: `velora worker` (or `--once` from cron).
