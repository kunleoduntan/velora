# VeloraERP v0.21.0 Validation Report

## Environment
- Source basis: supplied combined Velora 0.84.1 + VeloraERP 0.17.0 archive, updated in place.
- Runtime tests used the framework source bundled in the archive and SQLite test databases.
- No external database integration or browser E2E was available in this run.

## Completed checks
- Python `compileall`: passed for the application and test sources.
- JSON parsing and duplicate-field scan: 81 metadata JSON files validated; zero parse errors or duplicate fieldnames.
- Sales Order invoicing, stock-delivery gate, source lineage, credit limit, Sales Return conversion and realised margin integration tests: 20 passed.
- Account structure, enterprise design, Sales Quotation, metadata registry, finance smoke, finance reporting, invoice and party master tests: 35 passed.
- Sales pricing, inventory valuation, financial posting, landed-cost and cash transaction tests: 53 passed.
- Total: all 108 collected tests passed when executed in three focused batches.
- Python wheel build: passed (`velora_erp-0.21.0-py3-none-any.whl`).

## Suite execution
A single invocation of the complete suite exceeded the environment execution time limit after progressing beyond 75%. The complete 108-test population was then executed in three non-overlapping file groups; all groups passed.

## Not yet validated
- PostgreSQL and Oracle database integration.
- Multi-user concurrency/load testing on production database engines.
- Browser E2E for React Desk actions and reports.
- Security review of production role matrices, especially quarantine warehouse permissions and credit master-data permissions.
- Periodic Weighted Average final close reconciliation against realised margin report.
- Sales Return netting in margin reporting and automated replacement fulfilment.

## Known functional boundaries
- Sales Invoice conversion creates a draft only; no automatic submission or receipt.
- Stock invoice quantity is capped by submitted Delivery Notes; service/non-stock lines may be invoiced from the Sales Order.
- Credit limits are compared in company base currency; zero means unlimited.
- Sales Margin Analysis prefers Delivery Note issue cost when quantity coverage is complete; otherwise it shows invoice-time estimated cost.
- Complaint linkage is traceability only; it does not automatically create a return, credit note or replacement order.
