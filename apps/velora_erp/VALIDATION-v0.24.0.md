# VeloraERP v0.24.0 Validation Report

**Framework:** Velora 0.85.1  
**Application:** VeloraERP 0.24.0  
**Validation date:** 15 November 2026

## Delivered scope validated

- Purchase Invoice `Is Amortised Cost` and `Is Shared Cost` checkboxes.
- Conditional fields and collapsible layout sections.
- Monthly, Quarterly, Half-yearly and Yearly recognition periods.
- Start Date / End Date handling and period-count calculation.
- Read-only amortisation schedule preview.
- Automatic creation of approval-pending Recognition Schedules after Purchase Invoice posting.
- Independent maker-checker approval of generated Recognition Schedules.
- Prepayment asset posting followed by expense recognition through the central Financial Posting Engine.
- Cost Centre and Business Unit allocations with 100% allocation validation and rounding-residue handling.
- Intercompany Due From posting and durable outbox instruction.
- Combined amortisation and shared-cost allocation, including local and intercompany splits.
- Migration seeding for the dedicated `INTERCOMPANY_RECEIVABLE` Account Type.
- Finance workspace access to the Intercompany Cost Allocation outbox.

## Test results

The complete VeloraERP application test directory was executed in batches because a single combined invocation was not reliable in the available execution window.

| Test batch | Result |
|---|---:|
| Account structure, cash transactions, configuration, document flow, enterprise design, finance reporting | 40 passed |
| Finance smoke, financial posting engine, inventory, invoicing, landed cost | 33 passed |
| Metadata, party masters, new cost-treatment tests | 16 passed |
| Sales commercial, sales pricing, sales quotation | 30 passed |
| **Total VeloraERP application tests** | **119 passed** |

Additional framework regression tests:

- Selected framework tests: **92 passed, 3 skipped** (`test_document`, `test_schema`, `test_platform_engines`, `test_compat`, `test_api`).
- Git-based framework upgrade/rollback tests: 28 passed and 2 skipped in the executed subset, with 2 failures in existing update/rollback integration assertions. Those assertions concern the framework's Git release rollback harness and were not changed by this VeloraERP feature release. They remain open and are not represented as passing.

Other checks:

- Python compilation: passed.
- All VeloraERP JSON metadata files parsed successfully.
- Framework wheel build: passed.
- VeloraERP wheel build: passed.
- Isolated installation of both wheels and import/version check: passed.
- Quarterly date calculation smoke test: passed.

## Important functional boundary

Intercompany allocations post the source entity's debit to an Intercompany Receivable account and create an `Intercompany Cost Allocation` outbox record. **This release does not post the receiving entity's side into its separate database.** That requires the authorised cross-database intercompany delivery/acknowledgement service. Outbox records remain `Pending Counterparty Posting` until that service is implemented and acknowledges delivery.

## Not tested / outstanding

- PostgreSQL and Oracle end-to-end database integration.
- Cross-database intercompany counterparty posting, retry and acknowledgement.
- Browser end-to-end tests of the Purchase Invoice form and mobile layout.
- Concurrent submission/load testing for allocation and schedule generation.
- Production security certification and deployment rehearsal.

No production certification is claimed by this report.
