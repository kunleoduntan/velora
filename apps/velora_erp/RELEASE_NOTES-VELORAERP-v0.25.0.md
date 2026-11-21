# VeloraERP v0.25.0 — Finance Operations and Fixed Asset Lifecycle

**Framework compatibility:** Velora 0.85.1 (`>=0.85.1,<0.86`)

## Delivered

- Reused Financial Voucher as the native Journal Voucher; no duplicate manual-journal engine.
- Batch Bank Transaction with multiple receipt/payment rows, account validation, totals, approval and central ledger posting.
- Bank Transaction Processor with in-memory CSV parsing, SHA-256 duplicate import protection, deterministic coding rules, exception handling and draft bank-batch generation.
- Accrual and Accrual Line with multi-dimensional expense/liability postings and scheduled automatic reversal.
- Fixed Asset Category and protected Fixed Asset register.
- Fixed Asset Request with approval and conversion reference.
- Fixed Asset Purchase for direct acquisition.
- Purchase Invoice fixed-asset line capitalisation and creation of register records after the single invoice posting succeeds.
- Fixed Asset Lease for lessee-side IFRS 16 commencement, discounted schedule, interest/principal breakdown and Payment instalment settlement.
- Fixed Asset Revaluation with prior-loss reversal and reserve-release logic.
- Fixed Asset Disposal with derecognition, proceeds, costs, gain/loss and physical verification.
- Collapsible sections, conditional field dependencies, form/list scripts, Treasury workspace and Fixed Assets workspace.

## Accounting and security controls

All financial transactions post through the existing Financial Posting Engine. Source documents require approval, posted records are not casually cancellable, Fixed Asset financial fields are protected, bank processors cannot post without a separate approved batch, and lease settlement uses a row lock to prevent duplicate instalment settlement.

## Scope boundaries

The release does not claim complete fixed-asset or IFRS 16 lifecycle coverage. Lessor accounting, lease termination/modification, ROU depreciation posting, fixed-asset depreciation books and schedules, advanced bank reconciliation, bank-specific import adapters, multi-book revaluation and PostgreSQL/Oracle/browser/load certification remain future work. Full implementation boundaries are in `velora_erp/docs/FINANCE-OPERATIONS-AND-FIXED-ASSETS-v0.25.0.md`.

## Validation

The 19 VeloraERP test modules were executed in three batches. See `VALIDATION-v0.25.0.md` for exact results and outstanding environment coverage.
