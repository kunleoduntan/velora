# VeloraERP v0.6.0 — Start Here

## Release versions

- Velora Framework: `0.83.0`
- VeloraERP: `0.6.0`
- Required framework: `velora>=0.83,<0.84`

## What changed

VeloraERP now provides detailed immutable Account Ledger Records with source, date, currency, party, dimension, tax, settlement, inventory, fixed asset and organisational context. Account identity/classification is snapshotted at posting time for historical reporting.

The Finance reporting layer provides four perspectives over the same ledger:

1. General Ledger / Account Ledger
2. Customer Ledger
3. Supplier Ledger
4. Employee Ledger

Customer Statement and Supplier Statement remain available as separate presentation reports.

Employee is a Finance party identity supporting employee receivables and payables, including advances, loans, reimbursements and payroll-related liabilities. It is not a substitute for a full HR employee profile.

## Installation

Install the Velora Framework 0.83.x release first, then install VeloraERP 0.6.0. Apply the normal app migration/model-sync process so the new optional fields and report metadata are installed. The v0.6 post-model-sync patch refreshes the Finance workspace shortcuts.

## Key documentation

- `RELEASE_NOTES-VELORAERP-v0.6.0.md`
- `VALIDATION-v0.6.0.md`
- `velora_erp/docs/PARTY-LEDGERS-v0.6.0.md`
- `velora_erp/docs/SOURCE-ADAPTER-CONTRACT-v0.6.0.md`

## Accounting architecture

Party ledgers are not separate posting stores. Source modules continue to submit validated posting instructions to the central Financial Posting Engine, which remains the only writer of Account Ledger Records. Corrections use controlled reversals; posted ledger records are immutable.

## Scope boundary

This release establishes the ledger detail and party-ledger foundation. Universal Receipt and Payment documents, invoice settlement allocation, complete payroll integration and full HR integration remain later releases.
