# Validation Report — Velora 0.85.1 / VeloraERP 0.25.0

## Release artefacts

- Velora Framework wheel: `velora-0.85.1-py3-none-any.whl`
- VeloraERP wheel: `velora_erp-0.25.0-py3-none-any.whl`
- Source bundle: `velora-v0.85.1-veloraerp-v0.25.0-source.zip`

## Automated test results

All 19 VeloraERP test modules were executed in three batches:

| Batch | Test modules | Passed |
|---|---:|---:|
| Finance, metadata, configuration, reporting and new operations | 12 | 69 |
| Inventory, invoices, landed cost and Purchase Invoice cost treatment | 4 | 29 |
| Sales commercial, pricing and quotation | 3 | 30 |
| **Total** | **19** | **128** |

All 128 tests passed.

New integration coverage includes:

- CSV bank statement import, rule-based receipt/payment coding, generated batch approval and ledger balances.
- Accrual posting and scheduled reversal.
- Fixed Asset Request approval, Fixed Asset Purchase, Purchase Invoice capitalisation, revaluation and disposal.
- Fixed Asset financial-field protection.
- Lease commencement, present-value calculation, lease liability schedule and Payment settlement.
- Treasury and Fixed Assets workspace creation.

## Additional checks

- Python compilation: passed.
- JavaScript syntax check for DocType form/list scripts: passed.
- Metadata registry load: 89 DocTypes registered, including all new transaction and child DocTypes.
- Wheel build: both wheels built successfully.
- Isolated wheel installation: passed; imports report Velora 0.85.1 and VeloraERP 0.25.0.
- Isolated metadata registry load: passed.

## Test environment and limitations

- Functional integration tests use SQLite.
- PostgreSQL integration: not executed.
- Oracle integration: not executed.
- Browser end-to-end testing: not executed.
- Production concurrency/load testing: not executed. Lease settlement uses a row lock and duplicate-payment check, but this is not a substitute for a production concurrency test.
- Independent production security certification: not executed.

## Release status

**Development release validated on the tested SQLite environment.** It is not production-certified until PostgreSQL/Oracle, browser, concurrency/load and security validation have been completed in the target deployment environment.
