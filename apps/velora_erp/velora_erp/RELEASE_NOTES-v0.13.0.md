# VeloraERP v0.13.0

## GRNI Matching and Warehouse Transfers

### Added
- Purchase Receipt → Purchase Invoice Create From workflow, including partial uninvoiced quantity conversion and source-line traceability.
- Purchase Invoice line fields for Purchase Receipt, Purchase Receipt Line and GRNI Matched Quantity.
- GRNI clearing against original Purchase Receipt valuation, with Purchase Price Variance debit/credit for invoice price differences.
- Inventory Settings Purchase Price Variance Account.
- Final receipt locking and cumulative matched-quantity revalidation during Purchase Invoice submission.
- Stock Transfer and Stock Transfer Line DocTypes with independent approval and paired source/destination stock ledger movements.
- Moving-average carrying-value preservation across warehouse transfers.
- Serial-number warehouse reassignment during transfers and batch/serial validation.
- Stock Balance report derived from Stock Ledger Records.
- Inventory workspace shortcuts for Stock Transfers and Stock Balance.

### Accounting treatment
For a fully receipt-matched Purchase Invoice, the matched net invoice value clears GRNI at the original receipt base-currency value. Any difference between receipt value and invoice net value is posted to the configured Purchase Price Variance account. Input tax and supplier payable are posted as normal. Unmatched portions require an Expense Account.

Stock Transfers do not create financial postings because they move inventory within the same legal entity and do not change total inventory asset value.

### Validation
See `VALIDATION-v0.13.0.md` for the exact test commands and results. The complete app test suite exceeded the execution window when run as one process; individual test modules and targeted inventory/invoice tests were run separately.

### Limitations
Same-currency GRNI matching only; no FX remeasurement, three-way PO matching or price tolerance workflow. No in-transit transfers, opening stock migration, FIFO, reservation, historical as-at stock reporting or production database/browser/load/security validation.
