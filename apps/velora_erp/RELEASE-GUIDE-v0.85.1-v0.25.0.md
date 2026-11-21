# Release Guide — Velora Framework 0.85.1 / VeloraERP 0.25.0

## Package contents

- Velora Framework 0.85.1 wheel and source.
- VeloraERP 0.25.0 wheel and source.
- Finance Operations and Fixed Asset implementation guide.
- Validation report and release notes.

## Upgrade sequence

1. Back up the target legal-entity database and uploaded files.
2. Install/upgrade Velora Framework 0.85.1 using the site's normal deployment process.
3. Install/upgrade VeloraERP 0.25.0.
4. Run the normal Velora migration/model-sync process. The v0.23 patch creates Treasury and Fixed Assets workspaces.
5. Confirm the Finance Settings base currency, open financial period, account types and required asset/bank accounts.
6. Configure Fixed Asset Categories with asset and accumulated-depreciation accounts.
7. Configure Bank Transaction Coding Rules and test them with a small statement import.
8. Test a Bank Transaction Processor import, confirm the generated Batch Bank Transaction is still Draft, then approve and post it.
9. Test Accrual and automatic reversal in a non-production database.
10. Test one fixed asset purchase, revaluation and disposal in a non-production database.
11. For leases, configure the ROU asset, lease liability, interest expense and accumulated-depreciation accounts; confirm the generated payment schedule before commencement.

## Operational notes

- Use Financial Voucher for journal vouchers; no separate Journal Voucher DocType was added.
- Use Purchase Invoice for standard supplier invoices. Mark capital asset lines as Is Fixed Asset and complete category/name/life details.
- Use Fixed Asset Purchase for direct acquisition outside the standard Purchase Invoice route.
- The Bank Transaction Processor creates a draft posting batch; it does not post directly.
- Lease payment instalments are settled through Payment with purpose Lease Payment and exact scheduled principal/interest amounts.
- Fixed Asset depreciation posting, lease termination and lessor accounting are not part of this release.

## Validation and production readiness

SQLite automated tests passed in batches. PostgreSQL and Oracle integration, browser E2E, production concurrency/load and independent security certification remain outstanding. Do not treat the test results as production certification.
