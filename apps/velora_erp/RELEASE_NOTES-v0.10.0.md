# VeloraERP v0.10.0 — Operational Document Lifecycle

## Framework requirement

- Velora Framework `>=0.84,<0.85`.

## Added

- Sales Order and Sales Order Line.
- Delivery Note and Delivery Note Line.
- Waybill and Waybill Line.
- Purchase Order and Purchase Order Line.
- Purchase Receipt and Purchase Receipt Line.
- Sales Order → Delivery Note partial quantity conversion.
- Purchase Order → Purchase Receipt partial quantity conversion.
- Delivery Note → Waybill conversion.
- Source document and source line lineage on converted documents.
- Draft and submitted follow-on quantity tracking to prevent cumulative over-delivery and over-receipt.
- Generic framework REST endpoints for application-provided document-flow actions and Create From execution.
- React Desk `FormView` source updated for Create From ribbon actions; production frontend build remains pending.

## Accounting and inventory boundary

Sales Orders, Purchase Orders, Delivery Notes, Purchase Receipts and Waybills are operational documents in this release. They do not post financial ledger or inventory valuation entries. Sales and Purchase Invoices remain the financial recognition documents.

## Not included

- Credit Notes and Supplier Debit Notes.
- Sales Invoice → Delivery Note conversion.
- Sales/Purchase invoice allocation and outstanding-balance validation.
- Inventory movement, valuation, warehouses, batch and serial control.
- React Desk production bundle rebuild and browser-level end-to-end verification remain pending.

## Validation

See `VALIDATION-v0.10.0.md` for the tested scope and limitations.
