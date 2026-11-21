# VeloraERP v0.4.1 — Source Adapter Contract

## Summary

Formalises the integration boundary between source business documents and the central Financial Posting Engine.

## Delivered

- Added `PostingLine` and `PostingInstruction` immutable data contracts.
- Added the `SourcePostingAdapter` protocol.
- Added `post_source_document(source, adapter)` as the supported source-module entry point.
- Enforces submitted source state, typed posting instructions, three-letter currency, stable non-empty idempotency key (maximum 255 characters), and typed posting lines before delegating to the existing central engine.
- Added source adapter implementation guidance and an illustrative Sales Invoice adapter.
- Added tests for successful adapter posting, duplicate retry behaviour, unsubmitted source rejection and missing idempotency key rejection.

## Compatibility

- Requires Velora Framework `>=0.83,<0.84`.
- Existing direct Financial Posting Engine calls remain available for controlled internal flows and backwards compatibility.
- Existing Financial Voucher and Opening Balance Entry posting remain unchanged.

## Important transaction requirement

`post_source_document` must be called from the source document's submit lifecycle hook. The source submission and central posting must remain in the same database transaction. Do not commit between them.

## Not included

This release does not yet add Sales Invoice, Purchase Invoice, Payment, Receipt, Payroll, Inventory or Fixed Asset source DocTypes. It establishes the common contract those modules must implement.
