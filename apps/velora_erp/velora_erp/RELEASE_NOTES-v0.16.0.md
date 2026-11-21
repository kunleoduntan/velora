# VeloraERP v0.16.0 — Pricing Transparency and Margin Analysis

## Scope

This release extends the v0.15.0 Inventory Item pricing engine. It does not create a separate product master and does not change the central inventory valuation engine.

## Delivered

1. **Explain Pricing service** — returns the selected Inventory Item's cost, cost source, stock UOM conversion, transaction-currency cost floor, pricing policy state, selected basis and available candidate prices.
2. **Sales form action** — Sales Invoice and Sales Order now expose an Explain Pricing action. It requests the breakdown from the server; it does not calculate or authorise prices in the browser.
3. **Sales Margin Analysis report** — analyses submitted Sales Invoice lines using the cost snapshot stored on each line at invoice validation. It reports base-currency net sales, cost, gross profit and gross margin, with customer and item filters.
4. **Permission enforcement** — price explanations require read access to the relevant sales document. The report requires Sales Invoice read permission.
5. **Audit clarity** — the report explicitly identifies missing cost snapshots and explains that the snapshot is not the final FIFO issue cost or a later weighted-average closing adjustment.

## Pricing and cost policy retained

- Inventory Item is the stock master.
- Cost-based prices support Markup on Cost and Margin on Selling Price.
- Automatic priority remains Customer Group, Inventory Item, then Inventory Settings default.
- Fixed price and Manual price remain subject to the server-side cost floor.
- Line discounts, UOM conversion and foreign-exchange conversion remain part of the floor comparison.
- Delivery Note rechecks the actual warehouse issue cost, including FIFO issue layers.

## Important scope clarification

The v0.15.0 Sales Invoice and Sales Order metadata do not define a document-level discount field. Therefore, the cost-floor calculation in these documents includes the supported line-level discount percentage and per-unit discount amount. This release does not claim to apply a document-level discount that the current document model does not support.

## Deliberate boundaries

- Sales Quotation remains unimplemented as a VeloraERP DocType. Pricing support will be registered when the quotation document and its lifecycle are built.
- The margin report uses the cost snapshot recorded at invoice validation. It is not a substitute for realised COGS from Delivery Note stock issues, FIFO layer consumption or periodic Weighted Average closing.
- Below-cost override approvals are not introduced. A blocked sale must be repriced or the policy changed by an authorised administrator.
- Document-level discounts are not introduced in this release.

## Next recommended milestone

Build the Sales Quotation document lifecycle and conversion to Sales Order, then extend the pricing engine to quotation lines. After that, implement a realised gross-margin report reconciled to Delivery Note issue valuation and the inventory ledger.
