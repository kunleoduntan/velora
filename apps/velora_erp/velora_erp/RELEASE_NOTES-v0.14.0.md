# VeloraERP v0.14.0 — Inventory Valuation Methods and Controls

## Added
- Inventory Item valuation method now supports Moving Average, FIFO and Weighted Average.
- FIFO valuation reconstructs remaining receipt layers from immutable Stock Ledger Records and consumes the oldest cost layers first for issues and transfers. Warehouse transfers preserve individual FIFO receipt layers at the destination.
- Periodic Weighted Average is a distinct valuation policy. During the period, issues use a provisional perpetual average; an approved Inventory Valuation Closing calculates the period weighted average and posts a quantity-neutral closing valuation adjustment to inventory and Cost of Goods Sold.
- Inventory Valuation Closing protects closed posting periods against subsequent backdated stock movements. Overlapping period closes for the same warehouse scope are rejected.
- Opening Stock Entry imports approved opening quantities, valuation rates, warehouses, batches and serial numbers, debiting Inventory Asset and crediting a configured Opening Stock Clearing Equity account. It is permitted only before any stock ledger movement exists for the selected stock key.
- Stock Revaluation changes carrying value without changing physical quantity, with approval and central-engine accounting. FIFO layer values are adjusted proportionately.
- Inventory workspace shortcuts for Opening Stock Entries, Stock Revaluation and Inventory Valuation Closing.

## Valuation policy definitions
- **Moving Average:** perpetual weighted average recalculated as receipts are posted.
- **FIFO:** issues consume the oldest remaining receipt layers.
- **Weighted Average:** periodic weighted average using opening inventory and period receipts; period-end closing adjusts ending inventory and COGS to the final weighted rate.

Valuation method cannot be changed after stock movements exist. A controlled valuation migration is required.

## Accounting treatment
- Opening Stock Entry: Dr Inventory Asset / Cr Opening Stock Clearing.
- Positive Stock Revaluation: Dr Inventory Asset / Cr Stock Revaluation Gain (or configured Stock Adjustment Gain).
- Negative Stock Revaluation: Dr Stock Revaluation Loss (or configured Stock Adjustment Loss) / Cr Inventory Asset.
- Periodic weighted average closing: positive inventory adjustment debits Inventory Asset and credits COGS; negative adjustment debits COGS and credits Inventory Asset.
- FIFO stock issues use cost from consumed FIFO layers.

All financial entries use the central Financial Posting Engine. Stock Ledger Records remain immutable and authoritative for quantities and carrying values.

## Configuration
- Set the valuation method on each Inventory Item before stock movements begin.
- Configure Inventory Settings as before. Opening Stock Entry additionally requires an Opening Stock Clearing Account with Equity root type.
- Stock Revaluation gain/loss accounts are optional and fall back to Stock Adjustment Gain/Loss.
- Weighted Average requires an approved Inventory Valuation Closing for each valuation period and warehouse scope. Close periods before posting movements in later periods.

## Limitations
- Backdated stock movements and historical replay are not supported; closed periods and earlier posting dates are blocked.
- Periodic Weighted Average uses a manual approved close; no automated calendar scheduler or period-close orchestration is included.
- FIFO layers are reconstructed from Stock Ledger Records; legacy stock balances must be migrated through Opening Stock Entry before FIFO is enabled. Valuation method changes after movements are blocked.
- No stock reservation, in-transit transfers, historical as-at stock balance, stock ageing, serial warranty lifecycle, batch recall or full three-way PO/receipt/invoice tolerance workflow.
- React production build, browser E2E, PostgreSQL/Oracle integration, concurrency/load, external security and backup/restore rehearsal remain outstanding.
