# VeloraERP v0.5.0 — Start Here

This release builds the Customer and Supplier master-data and party-subledger foundation on top of the source adapter contract.

## Framework and app versions

- Velora Framework: `0.83.0`
- VeloraERP: `0.5.0`
- Required framework dependency: `velora>=0.83,<0.84`

## Customer and Supplier foundations

- Customer, Customer Group, Supplier, Supplier Group and Payment Terms are now available as Finance DocTypes in the native Velora Desk.
- Customer and Supplier records require valid default receivables/payables control accounts.
- Customer and Supplier Statements read directly from Account Ledger Records.
- Party balance and control-account reconciliation functions are available in `velora_erp.finance.party_accounting`.
- Customer credit limit and credit hold are master controls; enforcement during sales order/invoice processing is a later release.

## New source adapter API

Import the contract from:

```python
from velora_erp.finance.adapters import (
    PostingInstruction,
    PostingLine,
    SourcePostingAdapter,
    post_source_document,
)
```

Each source module implements `build_posting(source)` and returns a
`PostingInstruction`. Its submit hook calls `post_source_document(source,
adapter)` and stores the returned `Financial Posting Batch` name on the source.

The adapter must supply a stable idempotency key. It must not write ledger rows.
The source submission and financial posting must run in one database transaction.

## Read next

- `RELEASE_NOTES-v0.5.0.md`
- `velora_erp/docs/PARTY-MASTER-AND-SUBLEDGER-v0.5.0.md`
- `VALIDATION-v0.5.0.md`
- `RELEASE_NOTES-v0.4.1.md`
- `VALIDATION-v0.4.1.md`
- `velora_erp/docs/SOURCE-ADAPTER-CONTRACT-v0.4.1.md`
- `velora_erp/docs/FINANCIAL-POSTING-ENGINE-v0.3.0.md`

## Next milestone

Build the Sales and Purchasing transaction cycles, including invoice tax, inventory integration, customer receipts, supplier payments and settlement allocation.
