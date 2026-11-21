# VeloraERP v0.15.0 — Validation Report

## Automated tests

| Test batch | Result |
|---|---:|
| Sales pricing + document flow | 25 passed |
| Inventory ledger + invoice + landed cost | 23 passed |
| Remaining application modules | 44 passed |
| **VeloraERP application total** | **92 passed** |
| Framework API/workspace/report/scheduler tests | 43 passed, 1 skipped |

The full VeloraERP suite was attempted as a single process but exceeded the execution window. Every application test module was executed in bounded batches; all 92 tests passed.

## Static validation

- Python compileall: passed for `velora` and `apps/velora_erp/velora_erp`.
- JSON metadata: 74 files parsed successfully.
- Sales Invoice client script: `node --check` passed.
- Sales Order client script: `node --check` passed.
- Changed TypeScript/TSX source files: TypeScript `transpileModule` syntax diagnostics reported no errors.
- Velora Framework wheel: built as `velora-0.84.1-py3-none-any.whl`.
- VeloraERP wheel: built as `velora_erp-0.15.0-py3-none-any.whl`.
- Both wheels installed into an isolated target directory and imported successfully; versions 0.84.1 and 0.15.0 were confirmed.
- Combined and standalone source ZIP integrity: see final release packaging results.

## Important uncompleted validation

- React/Vite production build: not completed; `frontend/node_modules` was absent and `npm ci --offline` could not satisfy the package cache. Compiled `velora/desk/assets` therefore remains the prior build. React source changes are included in the source ZIP, but live row repricing will not activate until the Desk frontend is rebuilt and deployed.
- Browser end-to-end testing: not performed.
- PostgreSQL and Oracle integration: not performed.
- Concurrency/load and external security testing: not performed.
- Production backup/restore rehearsal: not performed.

## Behaviour covered by tests

- Markup on Cost and Margin on Selling Price arithmetic and half-up price rounding.
- Customer Group → Item → Default pricing hierarchy.
- Fixed-price mode and manual price cost-floor enforcement.
- Cost floor on Sales Order and Sales Invoice, including line discounts and foreign-exchange conversion.
- Last Purchase Cost refresh from Purchase Receipt and inclusion of Landed Cost Voucher allocation.
- Current Stock Ledger valuation fallback.
- Live pricing-provider REST endpoint and permission context.
- FIFO actual issue-cost recheck at Delivery Note submission.
- Purchase and sales UOM conversion factors through stock ledger movements.
- Existing invoice, return, GRNI, landed-cost, inventory valuation and document-flow regressions.
