# VeloraERP v0.20.0 — Realised Sales Margin

## Delivered
- Delivery Note stock issue captures the actual issue valuation rate and amount on each Delivery Note line.
- The values are derived from the same valuation engine used to write Stock Ledger Records and post COGS/inventory accounting.
- Sales Margin Analysis follows Sales Invoice → Sales Order Line → submitted Delivery Note Line.
- Where submitted delivery quantities cover the invoiced quantity, margin uses realised issue cost in base currency.
- Where coverage is incomplete or no delivery lineage exists, the report uses the invoice-time cost snapshot and labels it as an estimate.

## Interpretation
- Realised issue cost is actual perpetual issue valuation at Delivery Note posting. For periodic Weighted Average, final period-close valuation adjustments can still change final period COGS; this report does not independently re-run a period close.
- The report does not yet net Sales Returns from the original invoice margin. Return-aware net margin is a subsequent reporting enhancement.
