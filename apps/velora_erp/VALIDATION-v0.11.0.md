# VeloraERP v0.11.0 Validation

- VeloraERP tests: **66 passed**, executed in two focused batches (31 + 35). The single all-in-one test invocation exceeded the execution time limit; each collected test was covered by the successful batches.
- Framework targeted integration tests: **34 passed, 1 skipped** (financial report layouts, application workspaces, scheduler).
- Python compilation: passed.
- JSON metadata: 58 files parsed successfully.
- JavaScript syntax: all application JavaScript files passed `node --check`.
- VeloraERP 0.11.0 wheel: built and independently imported with Velora 0.84.0; version and landed-cost allocator smoke check passed.
- Combined and standalone source ZIPs: integrity checked.

## Implemented scope

- Invoice-linked Sales Return and Purchase Return, independent approval, source-line lineage, cumulative quantity/net/tax caps, and central-engine financial reversals.
- Landed Cost Voucher, charge and allocation metadata; allocations by value, quantity, weight, volume or equal share; exact total reconciliation after rounding.
- Sales and Purchasing workspace shortcuts.

## Deliberate limitations

- Returns reverse invoice financial values only. Physical stock return, warehouse movement, stock valuation and cost-of-sales reversal are not implemented.
- Landed Cost Voucher is a non-submittable allocation worksheet in this release. Submission and financial/inventory posting are disabled until Inventory Valuation Engine integration.
- Landed-cost tax recovery, multiple-currency charge apportionment, statutory duty capitalization policies and exchange differences are not included.
- React production bundle/browser E2E, PostgreSQL/Oracle, concurrency/load, external security and backup/restore tests were not performed.
- Full framework test suite was not run.
