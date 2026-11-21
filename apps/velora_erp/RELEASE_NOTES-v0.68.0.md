# VeloraERP v0.68.0 — Customer and supplier invoice settlement allocation foundation

- Validated Customer Receipt → Sales Invoice and Supplier Payment → Purchase Invoice allocation contracts.
- Partial and multiple invoice allocation proposals with deterministic FIFO ordering.
- Outstanding and unallocated amount safeguards; duplicate/over-allocation prevention primitives.
- Allocation reversals require reason and approval; no ledger entries are created.
- Cross-currency allocation is explicitly blocked until realised-FX posting is implemented.
