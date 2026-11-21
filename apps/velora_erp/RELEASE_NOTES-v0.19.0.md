# VeloraERP v0.19.0 — Customer Credit Management

## Delivered
- Credit Hold blocks Sales Order and Sales Invoice submission. A reason is mandatory when setting the hold.
- A positive Credit Limit is enforced in company base currency. Zero means unlimited.
- Exposure consists of customer receivables from Account Ledger Records plus remaining commitments on submitted Sales Orders.
- Remaining order commitments are reduced by quantities already represented by draft or submitted Sales Invoices.
- Foreign-currency orders and invoices are converted using their transaction exchange rates before comparison with the base-currency limit.
- Finance Settings can disable limit enforcement or exclude open Sales Orders from exposure. Credit Hold remains a separate explicit block while enforcement is enabled.
- Customer Credit Exposure report shows receivables, open order commitments, total exposure, limit, available credit and hold status.

## Policy
- No automatic override is provided. A user must resolve the credit hold or obtain a policy-approved credit limit change through authorised master-data access.
- Customer Credit Limit is stored in company base currency.
