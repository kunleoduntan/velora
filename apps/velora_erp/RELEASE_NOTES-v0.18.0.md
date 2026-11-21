# VeloraERP v0.18.0 — Sales Order Invoicing

## Delivered
- Sales Order → Sales Invoice is active and one-to-many.
- Conversion creates a draft invoice and never submits or posts it.
- Partial invoicing is tracked by immutable Sales Order Line references.
- Draft and submitted invoices reserve quantity; cancelled invoices do not.
- Source order is row-locked while billable quantities are calculated and the invoice is inserted.
- Revenue Account is required per Sales Order line at conversion; tax account/code/rate are carried forward.
- Agreed rates, discounts, tax and cost snapshots are copied from the order and checked on the server.
- Stock items are invoiceable only to the extent of submitted Delivery Notes; service/non-stock lines can be billed from the order.

## Controls
- No invoice quantity can exceed the Sales Order quantity.
- Stock item invoicing cannot exceed submitted delivered quantity.
- A line must reference a real line on the source order and retain its item, revenue account, tax account and agreed pricing values.
- Sales Invoice approval, current cost-floor validation and credit checks remain separate submission gates.

## Not included
- Automatic invoice posting, automatic receipt creation, and automatic settlement. The converter produces a draft Sales Invoice for review and approval.
