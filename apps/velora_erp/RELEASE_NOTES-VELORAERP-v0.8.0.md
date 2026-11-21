# VeloraERP v0.8.0

## Sales and Purchasing Invoicing Foundation

### Added
- Sales Invoice and Sales Invoice Line.
- Purchase Invoice and Purchase Invoice Line.
- Party control-account validation, due dates, external references and multicurrency context.
- Explicit tax account/code/rate/amount capture on invoice lines.
- Independent approval and immutable central-engine posting.
- Finance workspace shortcuts for both invoice types.

### Accounting entries
- Sales: Dr Customer Receivables (gross); Cr Revenue (net); Cr Output Tax (where entered).
- Purchase: Dr Expense account (net); Dr Input Tax (where entered); Cr Supplier Payables (gross).

### Not included
Orders, requisitions, credit/debit notes, invoice settlement allocation, outstanding/ageing, tax calculation/returns, inventory valuation/COGS integration, bank reconciliation and full credit-limit enforcement are not delivered in this release. See the v0.8.0 scope document.
