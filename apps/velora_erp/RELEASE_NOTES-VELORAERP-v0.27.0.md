# VeloraERP 0.27.0

**Release focus:** Fixed Asset Governance, Movement History and General Ledger Reconciliation.

- Added approved intra-entity Fixed Asset Transfer for location, Cost Centre and Business Unit changes.
- Added immutable Fixed Asset History Log and lifecycle event capture for acquisitions, lease commencement, depreciation, revaluation, impairment, disposal and transfers.
- Added Fixed Asset Reconciliation report comparing current register values with asset-linked immutable ledger balances.
- Corrected acquisition traceability so Fixed Asset Purchase and capitalised Purchase Invoice ledger lines carry asset references.
- Fixed Asset Purchase now stores acquisition cost and residual value in company base currency.
- Added Asset Transfer, Asset History and Asset GL Reconciliation shortcuts to the Fixed Assets workspace.

**Boundaries:** Multiple depreciation books, tax-vs-financial depreciation, component hierarchy, lease modification and termination are not included. The reconciliation report is current-state, not historical as-at. External database, browser, load and security certification remain outstanding.
