# VeloraERP v0.4.1 — Start Here

This release formalises how source business documents integrate with the central Financial Posting Engine.

## Framework and app versions

- Velora Framework: `0.83.0`
- VeloraERP: `0.4.1`
- Required framework dependency: `velora>=0.83,<0.84`

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

- `RELEASE_NOTES-v0.4.1.md`
- `VALIDATION-v0.4.1.md`
- `velora_erp/docs/SOURCE-ADAPTER-CONTRACT-v0.4.1.md`
- `velora_erp/docs/FINANCIAL-POSTING-ENGINE-v0.3.0.md`

## Next milestone

Proceed to Customer and Supplier master data, party validation and receivables/payables foundations. Build full Sales and Purchasing documents only after these foundations are established.
