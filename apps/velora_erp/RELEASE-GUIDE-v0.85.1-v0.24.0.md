# Velora Release Guide — Framework 0.85.1 / VeloraERP 0.24.0

## Release contents

- Velora Framework 0.85.1 source and wheel.
- VeloraERP 0.24.0 source and wheel.
- Purchase Invoice amortisation and shared-cost allocation metadata, controllers and tests.
- Recognition Schedule frequency/end-date enhancement.
- `INTERCOMPANY_RECEIVABLE` Account Type upgrade patch.
- Implementation guide and validation report.

## Upgrade notes

1. Back up each company database and application source before upgrading.
2. Install/upgrade the Velora Framework 0.85.1 package, then VeloraERP 0.24.0 using the deployment process already used for the environment.
3. Run the normal metadata migration/upgrade process so the new DocTypes and fields are created.
4. Ensure the post-model-sync patch `velora_erp.patches.v0_22.ensure_intercompany_account_type` has run. It is idempotent and adds the dedicated Account Type to existing companies.
5. Configure a Prepayment Asset account using Account Type `PREPAYMENT`.
6. For shared costs, configure active Cost Centres and/or Business Units. For intercompany, configure an Asset account using Account Type `INTERCOMPANY_RECEIVABLE` and the receiving legal entity identifier.
7. Test with a non-production Purchase Invoice before enabling the workflow for live transactions.

## Operational behaviour

- The invoice must be independently approved before submission, as before.
- Amortised invoice posting debits the Prepayment Account, not the expense account.
- Generated Recognition Schedules are Draft/Pending and require a separate Finance Manager/System Manager approval and submission.
- Due schedule periods are processed by the existing daily recognition scheduler.
- Shared-cost percentages must total exactly 100%.
- Intercompany outbox records are not a substitute for a completed counterparty posting. They remain pending until a separate cross-database service acknowledges delivery.

## Validation

See `VALIDATION-v0.24.0.md` and `velora_erp/docs/PURCHASE-INVOICE-AMORTISATION-AND-SHARED-COST-v0.24.0.md`.
