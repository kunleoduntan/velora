# VeloraERP v0.75.0 — Framework settlement allocation integration

- Added a framework transaction adapter contract for allocation persistence inside the host-owned transaction.
- Locks source settlement and target invoice before checking balances and party/company/currency alignment.
- Enforces posted-source/target status, idempotency and source/target available-balance limits.
- Adapter never commits independently and does not create GL entries; caller owns atomic transaction and persistence.
- Production adapter implementation must be bound to the actual Velora database transaction manager and row-lock API.
