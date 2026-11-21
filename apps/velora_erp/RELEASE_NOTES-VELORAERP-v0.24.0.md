# VeloraERP v0.24.0 — Purchase Invoice Amortisation and Shared Cost Allocation

## Delivered

- Purchase Invoice `Is Amortised Cost` checkbox with frequency, start date, end date and prepayment account.
- Read-only amortisation schedule preview with period dates and amounts.
- Automatic creation of approval-pending Recognition Schedules after approved Purchase Invoice posting.
- Monthly, Quarterly, Half-yearly and Yearly recognition frequencies, with end-date-derived period count.
- Purchase Invoice `Is Shared Cost` checkbox and allocation table for Cost Centre, Business Unit and Intercompany allocations.
- Server-side 100% allocation validation and deterministic rounding.
- Cost Centre and Business Unit dimensions flow into central financial posting and future amortisation recognition.
- Intercompany Due From posting and auditable `Intercompany Cost Allocation` outbox instruction.
- Dedicated `INTERCOMPANY_RECEIVABLE` Account Type, seeded for new installations and added to existing companies by migration patch.
- Collapsible Purchase Invoice form sections and conditional visibility/mandatory rules.

## Important intercompany boundary

The source legal entity posts its Due From Affiliate balance and creates an outbox instruction. Automatic receiving-entity posting across separate company databases is not included in this release and must be completed by the authorised cross-database intercompany service. The outbox remains Pending Counterparty Posting until that service is implemented and acknowledges delivery.

## Compatibility

Existing Payment and Receipt Recognition Schedules remain compatible. Schedules without an End Date continue to use their existing Period Count and default to Monthly frequency.

## Validation

See `VALIDATION-v0.24.0.md`. SQLite application tests are executed in batches. PostgreSQL/Oracle integration, cross-database intercompany delivery, browser E2E and production load testing remain outstanding.
