# VeloraERP v0.15.0 — Inventory Pricing and Cost Protection

## Release summary

This release generalises the supplied pharmacy margin-pricing approach to VeloraERP's **Inventory Item** master and adds a server-enforced selling cost floor.

### Selling price policy
- Added Inventory Item Pricing Mode: Margin Based or Fixed Price.
- Added Item Selling Margin and Standard Selling Rate.
- Added Customer Group Selling Margin with nearest-parent inheritance.
- Added Inventory Settings for Markup on Cost / Margin on Selling Price, default margin, rounding, cost basis, manual pricing, strict price configuration and below-cost blocking.
- Added Price Basis on Sales Order and Sales Invoice lines: Automatic, Customer Group, Item, Default and Manual.
- Added read-only Customer Group Price, Item Price, Default Price, Cost Rate, Cost Source and Price Applied details.
- Automatic price hierarchy is Customer Group → Inventory Item → default Inventory Settings.
- Manual and fixed prices remain subject to cost-floor enforcement.

### Cost basis and landed costs
- Added system-maintained Last Purchase Cost, Last Purchase Date, Last Purchase Reference and Cost Source snapshots to Inventory Item.
- Last Purchase Cost is sourced from the latest submitted Purchase Receipt and includes allocated Landed Cost Voucher amounts.
- Purchase Receipt and Landed Cost Voucher submission refresh the snapshot; the v0.15 upgrade patch refreshes existing inventory items.
- Current Stock Ledger valuation and Inventory Item Standard Cost Rate provide controlled fallbacks.

### Server-side cost floor
- Sales Order and Sales Invoice reject net selling prices below cost after line discounts and exchange-rate conversion.
- Stock items without a positive cost are blocked when Require Cost Before Selling Stock Items is enabled.
- Delivery Note inherits its agreed price and discount context from the Sales Order, rechecks current cost, and checks actual warehouse issue cost immediately before stock posting. FIFO dispatch uses the actual cost layers consumed.
- Sales Returns remain return documents and are not treated as new sales.

### UOM conversion
- Added stock-UOM conversion factors to commercial purchase, receipt, sales, delivery and return lines.
- Stock Ledger movements convert document quantities to stock units.
- Purchase Receipt valuation rates are converted to stock-unit cost; landed-cost quantity allocations use stock quantities.
- Delivery Note and Purchase Receipt inherit conversion factors from their source orders; return documents inherit them from source invoices.

### Native Desk integration
- Added generic `document_pricing_provider` discovery and `POST /api/document-pricing/{doctype}`.
- Extended React Desk source with child-row events, row update support and a live pricing Form API.
- Added Sales Invoice and Sales Order client scripts.
- **Build limitation:** the compiled Desk assets were not regenerated because frontend dependencies were unavailable. Server-side price calculation and cost-floor protection work; live row repricing requires a production frontend rebuild. Older Desk runtimes receive a clear message instead of a client-script exception.

## Validation

- VeloraERP application tests: 92 passed across three batches.
- Framework targeted tests: 43 passed, 1 skipped.
- 74 JSON metadata files validated.
- Python compilation passed.
- Sales Invoice and Sales Order JavaScript syntax checks passed.
- Changed TypeScript/TSX files passed compiler transpilation syntax checks.
- Velora 0.84.1 and VeloraERP 0.15.0 wheels built and passed isolated import checks.
- Wheel builds and isolated imports are reported in the validation file.

The full app suite exceeded the single-process execution window; all test modules were run in batches. The React production build, browser E2E, PostgreSQL/Oracle integration, concurrency/load and external security tests were not performed.

See `docs/SELLING-PRICING-AND-COST-PROTECTION-v0.15.0.md` for the complete policy and cost-basis details.
