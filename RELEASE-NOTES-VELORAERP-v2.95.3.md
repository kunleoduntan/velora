# VeloraERP 2.95.3 - selling price built on the cost you choose, and a profit floor
- **Cost Used for Pricing** (Inventory Settings): Last Purchase Cost, **Average of Last Purchases** (3 to 5 purchases, weighted by quantity, landed cost included), **FIFO (Oldest Stock on Hand)**, **Highest of These (Safest)**, or Current Inventory Valuation. The selling margin and the cost floor are both built on the chosen cost.
- **One policy, three levels**: set it once in Inventory Settings; an **Item Group** (and its sub-groups) or a single **Item** can choose a different one. Both default to "Follow Settings", so nothing needs configuring per item. Order: Item, then Item Group, then Inventory Settings.
- **Minimum Profit (%)**: never sell below cost plus this percentage (0 = just not below cost). Checked on the invoice/order and again at dispatch against the real issue cost, so a FIFO cost that has moved cannot slip a loss through.
- "Highest of These" takes the dearest of last purchase, average, FIFO and current valuation, so whichever method turns out to be the real cost, the sale still makes a profit.
- If the chosen method has no data yet (for example no purchase yet), the system uses current stock valuation, else the dearest known cost, and the price note says so.
- Explain Price now also returns every method's cost, the basis in force and where it came from, and the lowest allowed rate.
- Checked by tests: purchases at 200, 100, 150 give last 150, average 150, FIFO 200, highest 200; item and item-group overrides; a sale 5 under the floor is refused and one at the floor accepted.

Limits: FIFO cost is read from the stock ledger for the warehouse on the line, or the oldest layer anywhere when none is given. The average covers purchase receipts only (not opening stock). The sales screen's own live-price display was not changed; it takes the new cost through the same pricing code.
