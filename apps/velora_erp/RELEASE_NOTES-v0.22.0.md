# VeloraERP v0.22.0 — Enterprise Settings Governance Foundation

## Release objective

Establish governed configuration as a reusable platform capability before adding further enterprise business policies. Settings are data contracts and never executable Python, SQL or JavaScript.

## Delivered

### Velora Framework 0.85.0
- `velora.settings_governance` engine with a typed Settings Catalogue.
- Company-database-local change requests and immutable published versions.
- Scope controls for legal entity, branch, module, role and user. Legal-entity settings remain isolated in each entity database.
- Explicit legal-entity fallback only; no implicit universal inheritance.
- Effective-date resolution, mandatory reason, maker-checker and critical-setting dual approval.
- Type validation, secret reference validation, high-risk backdate prevention and append-only audit records.
- SHA-256 checked configuration packages. Import stages changes as Draft and never auto-approves or publishes them.
- REST endpoints under `/api/settings`.

### VeloraERP 0.22.0
- Framework compatibility updated to `>=0.85.0,<0.86`.
- Existing Finance Settings and Inventory Settings remain intact and operational.
- No automatic conversion of existing settings records was performed. A later domain-by-domain migration will require mapping, validation and reconciliation.

## Important operational notes

- All governance records live in the active company database; the engine does not introduce a shared operational settings database.
- Only Administrator or System Manager can administer the catalogue and settings changes.
- Critical settings require two distinct approvers in addition to the maker.
- Secret values must be stored in the secret facility; the catalogue accepts references such as `secret://integration/name`, never raw credentials.
- Package import creates Draft requests. The target entity must validate, approve and publish independently.
- Published versions are append-only. A correction is a new change request, not an edit to history.

## Validation status

See `VALIDATION-v0.22.0.md`. PostgreSQL/Oracle integration, browser E2E, concurrency/load and production security testing remain separate release gates.
