# VeloraERP v0.21.0 — Sales Returns and Customer Complaints

## Delivered
- Sales Invoice → Sales Return Create From supports partial returns and carries source invoice line, item, quantity, UOM, account, tax and cost valuation references into a draft return.
- Previously returned quantities and amounts are considered; source invoice locking and server-side validation prevent cumulative returns above invoiced values.
- Return amounts and tax are apportioned proportionally using half-up currency rounding.
- Return disposition is Restock or Quarantine. Quarantine requires a Warehouse explicitly designated as a quarantine warehouse.
- Restock can be gated by a passed quality inspection status and inspection reference.
- Customer Complaint DocType records customer, related submitted invoice/delivery, category, severity, assignment, root cause, resolution, related return and replacement Sales Order.
- Complaint status transitions are constrained and resolved/closed complaints require a resolution and date.
- Added Customer Complaint Register and Sales workspace shortcuts.

## Boundaries
- A complaint does not automatically create a return, credit note or replacement order. Those remain separately approved transactions linked back to the complaint.
- Quarantine stock is posted into the designated quarantine warehouse; users must prevent that warehouse from being used for saleable fulfilment through warehouse and permission policy.
- Scrap/write-off disposition and automatic replacement fulfilment are not part of this release.
