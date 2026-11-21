# VeloraERP v0.77.0–v0.79.0

## v0.77.0 — Native Party Adjustment Definition
Adds the Party Adjustment metadata for Customer Credit Notes and Supplier Debit Notes and a controlled lifecycle service with maker-checker separation, status transitions, immutable posting reference requirements and duplicate-safe adjustment identity.

## v0.78.0 — Party Statements and Ageing
Adds read-only party statement and ageing services over an injected ledger source. The adapter is intentionally read-only; it does not synthesize ledger entries or post journals.

## v0.79.0 — AR/AP Cycle Orchestration
Adds repository contracts to orchestrate adjustment lifecycle changes with audit events and validates that posting references point to an actual Posted Financial Posting Engine batch for the adjustment. Repository implementations must use one framework-managed transaction.

## Integration boundary
These are application services and metadata contracts. Production rollout still requires concrete Velora database repository/source adapters, permission registration, UI forms and integration tests against a deployed database. No claim is made that a live deployment was exercised here.
