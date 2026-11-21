# VeloraERP v0.71.0 — Controlled settlement allocation register

- Added transactional SQL allocation register with unique idempotency keys and source/target indexes.
- Added persistent Customer Receipt → Sales Invoice and Supplier Payment → Purchase Invoice allocations.
- Added cumulative source-balance checks, maker-checker approval validation and independent reversal approval.
- Partial allocation reversals retain full history; fully reversed allocations become Reversed.
- Allocation register never creates ledger entries; production database adapter requires host transaction/row-lock integration.
