# VeloraERP v0.11.0 — Returns and Landed Cost Foundations

## Delivered
- Sales Return and Purchase Return are the canonical return DocTypes. Separate credit-note/debit-note DocTypes are intentionally not used.
- Create From supports Sales Invoice → Sales Return and Purchase Invoice → Purchase Return.
- Return documents inherit source invoice, party, currency, exchange rate, source invoice line, revenue/expense account, tax account and tax metadata.
- Partial returns support quantity-based conversion where invoice line quantity is supplied. Cumulative quantity, net amount and tax reversal are capped against the original invoice line.
- Return submissions require independent approval and post financial reversals through the central Financial Posting Engine.
- Added Landed Cost Voucher, Landed Cost Charge and Landed Cost Allocation metadata.
- Landed cost calculation supports allocation by value, quantity, weight, volume and equal share, with exact total reconciliation after rounding.
- Added Sales and Purchasing workspace shortcuts.

## Accounting treatment
- Sales Return: debit original revenue/contra-revenue account and output tax account; credit Customer Receivables.
- Purchase Return: debit Supplier Payables; credit original expense and input-tax accounts.
- These are invoice-linked financial reversals. Physical inventory movements and valuation/COGS effects are not yet implemented.

## Deliberate limitation
Landed Cost Voucher is an allocation worksheet only in v0.11.0. The DocType is deliberately non-submittable; financial and inventory posting are deferred until the Inventory Valuation Engine can capitalise eligible charges into stock valuation and subsequent cost of sales.

See `velora_erp/docs/RETURNS-LANDED-COST-v0.11.0.md` and `VALIDATION-v0.11.0.md`.
