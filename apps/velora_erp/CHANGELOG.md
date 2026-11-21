## v0.22.0 — Enterprise Settings Governance Foundation

- Added the reusable Velora Settings Governance Engine in the framework, with typed setting catalogue definitions and explicit legal-entity, branch, module, role and user scopes.
- Added effective-dated, immutable published setting versions; exact-scope resolution and explicitly declared legal-entity fallback only.
- Added mandatory business reasons, maker-checker approvals, and dual independent approval for critical settings.
- Added typed value validation, high-risk backdating prevention and secret-reference-only configuration values.
- Added audit history, settings version history, configuration package export with SHA-256 integrity verification, and safe import as draft changes only.
- Added company-local REST APIs for catalogue, change requests, effective values, audit, versions and package promotion.
- Preserved the existing Finance Settings and Inventory Settings DocTypes; this release does not silently migrate their current values into the new catalogue.
- Requires Velora Framework >=0.85.0,<0.86.
