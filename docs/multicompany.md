# Database-per-company architecture (Velora control plane)

This is how Velora implements the "one platform, one identity, one database per company" design, what is built, and where it
deliberately differs from the proposal.

```
                    VELORA CONTROL PLANE  (its own database - identity and routing only, never business records)
   cp_tenant · cp_company (registry) · cp_user · cp_user_company (roles per company) · cp_session · cp_secret · cp_audit
                                  │
                         Database Router  (request-scoped, pooled)
              ┌───────────────────┼───────────────────┐
         Company A DB        Company B DB        Company C DB      ← each: its own tables, series, apps, settings
```

## The eight components

| Proposed component | Where it is | Status |
|---|---|---|
| Tenant Registry | `controlplane/registry.py`, `cp_tenant` | Built |
| Company Registry | `cp_company`: engine, host, port, database, user, **secret reference**, status, schema version, provisioning status/error | Built (every field the proposal lists) |
| Database Manager | `dbadmin.py`, `provision.backup_database` | Built (create/drop/check/backup PostgreSQL; SQLite for development) |
| Database Router | `controlplane/router.py` | Built: per-company connection pool, LRU eviction, picks up apps installed by another process |
| Database Provisioning Engine | `controlplane/provisioning.py` | Built: creating_database → initializing → installing_apps → ready; on failure it records the error and removes what it created |
| User Company Access | `cp_user_company` | Built, **with roles per company** |
| Company Context Manager | `company.py`, `ControlPlane.company_scope`, `api/platform.py` | Built |
| Company Switch API | `POST /api/auth/switch-company` + the `X-Velora-Company` header | Built |
| Group Consolidation Engine | - | **Not built** (needs the financial engine first) |

## Rules from the proposal, and how they are enforced

- **No mutable global "active database".** The company/site/session are context variables set per request; nothing is switched globally.
  Tests fire 40 (SQLite) and 90 (PostgreSQL, three databases) simultaneous requests alternating between companies and assert that every record
  lands in the right database and that numbering stays gap-free per company.
- **Passwords never stored in the registry.** The registry holds `secret_ref`. References are `local:<id>` (Fernet-encrypted in `cp_secret`; the
  master key is in `VELORA_MASTER_KEY` or `platform/master.key`, mode 600, never in the database), `env:NAME`, or `file:/path`
  (Docker/Kubernetes secrets). A test proves the password appears in neither the registry row nor the ciphertext.
- **Validate access on every request.** Each request re-checks the session, the company, the user's membership and the company status.
  "No such company" and "not yours" return the identical error so company existence is never revealed.
- **Seamless switching.** Sign in once; the Desk keeps the chosen company *per browser tab* (sessionStorage) and sends it on every request,
  so two tabs can work in two companies at the same time. The server-side session also remembers a default company.
- **Independent numbering, masters and transactions.** Company A and B can both hold `Customer 001` and `INV-00001`; they are different rows in different databases.
- **Shared code, separate data.** One installed codebase; each company database records which apps are installed (`velora_installed_app`).
  Different companies may run different app sets.

## Where Velora differs from the proposal

1. **Roles live in the control plane, per company.** A company database holds no users. Alice can be *System Manager* in A and *Sales User* in B;
   her roles are loaded into the request for the company she is in. (Verified: export and delete are allowed in A and refused in B.)
2. **A platform administrator is not automatically an administrator inside companies.** Access to company data is always an explicit grant.
3. **Company per tab, not only per session.** The proposal's flow stores the active company on the session; that breaks with two tabs. Velora uses
   the session value only as a default.
4. **"Sites" still exist** (a standalone single-database deployment with developer-mode sign-in). The platform is the production architecture;
   unifying the two is future work.

## Authentication (new)

scrypt password hashing with per-user salt; opaque session tokens stored only as SHA-256; sessions slide for 12 h idle with a 7-day cap;
5 wrong passwords lock the account for 15 min; identical errors for unknown user / wrong password (and equal CPU cost);
changing a password signs out every session; HttpOnly + SameSite=Lax cookies with `Secure` behind HTTPS; a required `X-Velora-Request` header on
cookie-authenticated writes (CSRF); Bearer tokens for API clients; every sign-in, failure, grant, switch and provisioning step in `cp_audit`.

## Not built yet (be aware before relying on it)

- Group consolidation (combined trial balance, intercompany elimination, currency translation).
- Per-company customization beyond the theme (each company already has its own theme setting): Custom Fields, workflows, print formats, dashboards and other company settings. Today a company's
  data model is the DocTypes of its installed apps. The "versioned migrations that never overwrite customizations" rule only becomes meaningful once these exist;
  today migrations are additive and `velora migrate --all-companies` rolls an upgrade through every company (a failure never blocks the others; `company list` flags schema drift).
- MFA / SSO, password reset by email, per-IP rate limiting (only per-account lockout), an admin UI (everything is CLI), master-key rotation, control-plane high availability.
- A per-request cache for sessions/access (every request makes a few small control-plane queries; correct and immediately revocable, but a cache will be needed at scale).
- Cross-company reads in one request (deliberate: consolidation must be a separate, authorised engine).

## v0.9 company roles and duplication

The Control Plane retains the minimum membership index (`user ↔ company`) needed to resolve a user's permitted company environments. The authoritative role list for that user is stored in `velora_company_user_role` inside that company's own database. This keeps role assignments company-specific. Legacy `cp_user_company.roles` values are migrated to the company database on first access for backward compatibility.

Platform administrators can create companies from the Desk. A company duplication operation always provisions a new database. The administrator selects which DocTypes (in dependency order) and company settings to copy. The selected data is imported through normal document validation and hooks; it is not a live link, shared master-data pool or ongoing synchronization process. User membership is not copied automatically.
