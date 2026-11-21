# VeloraERP v0.74.0 — Credit and debit note transaction lifecycle

- Added a credit/debit note lifecycle with Draft, Pending Review, Approved, Rejected, Posted and Cancelled states.
- Enforced independent review and approval; maker cannot approve own adjustment.
- Posting requires a Financial Posting Engine callback and explicit posting batch reference.
- Posting payload carries deterministic idempotency key and never creates ledger entries itself.
- Validates source invoice status, party/document pairing, currency, amount and ISO posting date.
