# VeloraERP v0.12.0 — Inventory Ledger, Stock Reconciliation and Landed Cost Capitalisation

**Framework:** Velora 0.84.0  
**Application:** VeloraERP 0.12.0

## Delivered

- Inventory Item, Warehouse, Batch, Serial Number, Stock Ledger Record, Stock Reconciliation and Inventory Settings.
- Physical stock count table showing current stock balance, physical count, calculated adjustment, current cost, proposed price, current value and value adjustment.
- Independent approval and immutable stock ledger adjustment posting.
- Moving-average stock valuation with proposed price used for positive stock variances and current cost used for shortages.
- Serial-number and batch tracking with item ownership validation.
- Stock movements and financial postings for Purchase Receipt, Delivery Note, Sales Return and Purchase Return.
- Landed Cost Voucher capitalisation into inventory valuation, with the consumed portion adjusted to Cost of Goods Sold.
- Inventory Settings and a dedicated Inventory workspace.
- Backdated stock movements blocked per item/warehouse/tracking key.

## Accounting controls

All inventory accounting uses the central Financial Posting Engine. Purchase Receipt debits Inventory Asset and credits Goods Received Not Invoiced; Delivery Note debits Cost of Goods Sold and credits Inventory Asset; returns reverse the relevant inventory cost effect; stock reconciliation uses configured adjustment gain/loss accounts; landed costs debit inventory or Cost of Goods Sold and credit the originating charge accounts.

## Important limitations

Moving Average only; no FIFO, stock transfer, opening stock entry, stock reservation, stock revaluation, historical reposting, or Purchase Invoice-to-GRNI matching yet. Backdated inventory movements are rejected. See `velora_erp/docs/INVENTORY-LEDGER-AND-STOCK-RECONCILIATION-v0.12.0.md`.
