# Hosting Velora

## Read this first: authentication

**Platform mode has real sign-in** (`velora platform init`): users and passwords live in the control plane, sessions are HttpOnly cookies,
and a user only reaches the companies they were granted. See `docs/multicompany.md` for the design and its limits.
Still missing: MFA/SSO, password-reset email and per-IP rate limiting, so keep an HTTPS reverse proxy in front and consider an IP allow-list or VPN for admin use.

**Developer-mode sites** (`new-site --developer-mode`) trust an `X-Velora-User` header from whoever calls. Never expose one to a network.
A site created without it refuses every API call.

HTTPS is required in production: the session cookie is only marked `Secure` when the request arrives over TLS (the nginx file forwards `X-Forwarded-Proto`).
**Back up `platform/master.key` separately from the databases** - without it the stored company database credentials cannot be decrypted.

## The three models, and what each needs

| Model | What it means | What it needs |
|---|---|---|
| **Self-hosted** | A client installs Velora on their own server | `pip install velora` + PostgreSQL + a reverse proxy. Nothing from you except the app |
| **Velora Cloud** | You run many clients on one server: platform mode (one control plane, one PostgreSQL database per company, sign-in once, switch company) or workspace sites (Host header → site) | A server you control (root), PostgreSQL where Velora can create databases, nginx + TLS, backups |
| **Developer distribution** | Others publish/install apps | A git host (GitHub etc.) and later PyPI/a registry. `velora get-app <git-url>` already works. Hosting is irrelevant |

## CloudClusters

What the public CloudClusters pages show (verify current plans and specs yourself before buying):

| Product | Fits Velora? |
|---|---|
| **Managed ERPNext hosting** (one-click, containers on Kubernetes) | **No.** It runs ERPNext only, and cannot run Velora. Keep your existing bench there, unchanged |
| **Managed PostgreSQL** (database + user created in the control panel) | **Yes, as the database**, in *bring-your-own-database* mode (below). One database per site, created in the panel |
| **Python hosting** (upload by FTPS, Nginx in front) | **Doubtful.** The page I found listed Python 3.8; Velora needs **3.10+**, and it is a long-running server with a CLI, not an uploaded script. Ask them whether newer Python and background processes are supported |
| **VPS / dedicated servers** | **Best fit for Velora Cloud**, but the CloudClusters site refers VPS to a *sister company* - confirm plans, root access and location with them |

So: **you can host on CloudClusters infrastructure only if you take a VPS (root) - or a managed PostgreSQL plus an app
server somewhere else.** The managed ERPNext product cannot host Velora, and any generic "Python hosting" plan must first be
proven to run Python 3.10+ and a persistent process.

### Bring-your-own-database (managed PostgreSQL)

Managed hosts give you a database and a login, not superuser rights, so Velora cannot create databases itself there:

```bash
# 1. In the host's control panel: create database + user for the site
# 2. Tell Velora about it (it checks the connection and refuses a wrong password)
velora new-site erp.client-a.com --db-host <host> --db-port <port> \
    --db-name <database> --db-user <user> --db-password '<password>'
```

`velora drop-site` never drops a database it did not create. Each new client site means one more database in the panel;
on a VPS where you run PostgreSQL yourself, `--db-root-password` makes this automatic.

## Recommended path: one VPS, Velora Cloud

Ubuntu 24.04 LTS, 2+ vCPU / 4+ GB RAM to start (my estimate, not a benchmark - measure with your own data), SSD, root access.

```bash
apt install -y python3-venv postgresql nginx certbot python3-certbot-nginx git
useradd -m -d /srv/velora velora && su - velora
python3 -m venv /srv/velora/venv && /srv/velora/venv/bin/pip install "velora[postgres]"   # or: pip install /path/to/velora-x.y.z.whl
cd /srv/velora && /srv/velora/venv/bin/velora init myworkspace && cd myworkspace

export VELORA_DB_ROOT_PASSWORD='<postgres superuser password>'
velora new-site erp.client-a.com                 # --db postgres is implied by the root password; creates role + database
velora get-app https://github.com/you/governmentone.git
velora --site erp.client-a.com install-app governmentone
```

Then, as root: install `deploy/velora.service` (systemd), `deploy/nginx.conf` (set your domain; run `certbot --nginx`),
and schedule `deploy/backup-all.sh` from cron. nginx **must** forward `Host` - that is how requests find their site.

**Many client domains:** point each domain's DNS at the server, create a site named exactly like the domain
(`velora new-site erp.client-b.com`), add the domain to nginx (or use a wildcard server block + wildcard certificate).
A request whose Host matches no site gets `404 SiteNotFound`. To answer unknown hosts (e.g. access by IP) set
`"default_site": "<site>"` in `config/common.json`.

**Docker alternative:** `deploy/docker-compose.yml` + `deploy/Dockerfile` (PostgreSQL + Velora, workspace and data on volumes).

### Operations checklist
- **Backups:** `velora --site X backup` (PostgreSQL via `pg_dump`, SQLite consistent copy); `deploy/backup-all.sh` runs it for every site and prunes after 14 days.
  A backup that stays on the same server is not a backup - copy it off-site (the script has the rsync line) and **test a restore** before you rely on it. `velora restore` is not built yet (restore with `psql`).
- **Secrets:** workspace sites keep their database password in `site_config.json` (mode 600). Platform mode keeps company credentials encrypted in the control plane; `platform/master.key` (mode 600) is the only thing that can decrypt them. Keep the workspace out of git (`velora init` writes a `.gitignore`).
- **Upgrades:** `pip install -U velora`, then `velora --site X migrate` for every site, or `velora migrate --all-companies` in platform mode. Migrations only *add* tables/columns/indexes; they never drop or change data.
- **Isolation:** one database + one database role per site; a request is bound to exactly one site, validated against `sites/<host>`.
- **Not built yet:** MFA/SSO, background workers/scheduler, email, file uploads, per-company resource limits, zero-downtime upgrades, a restore command.

## What I tested, and what I could not

Tested in this sandbox: clean-virtualenv `pip install` from the built wheel (Desk UI included) → `init` → two PostgreSQL sites
provisioned by Velora → app + DocType scaffold → install on one site → one process serving both by Host header → isolation,
unknown-host refusal, Excel export → backup → drop (database and role removed); bring-your-own-database; install rollback
on a failing hook; the nginx config (`nginx -t`) and `backup-all.sh`.

**Not run here:** the Dockerfile/compose (no Docker in the sandbox), the systemd unit's behaviour (syntax parsed only),
TLS/certbot, and anything on CloudClusters itself.

## Updating a hosted installation
See `docs/upgrading.md` for `velora update` / `velora upgrade`, maintenance mode, automatic rollback and per-hosting recipes (VPS, Docker, managed PostgreSQL). `deploy/install.sh` sets up the restart hook that `velora update` uses.
