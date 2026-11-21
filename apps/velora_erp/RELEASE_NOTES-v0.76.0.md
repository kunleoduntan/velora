# VeloraERP v0.76.0 — Customer and supplier control-account reconciliation

- Added customer/supplier subledger-to-control-account reconciliation by company, control account, currency and as-of date.
- Added current, 1–30, 31–60, 61–90 and over-90-day ageing buckets.
- Added tolerance-based reconciliation status and deterministic reconciliation identifiers.
- Differences produce reviewable exception records; no automatic journal or ledger adjustment is created.
- Service accepts supplied open-item and GL balances; live database query wiring and browser workbench remain deployment integration tasks.
