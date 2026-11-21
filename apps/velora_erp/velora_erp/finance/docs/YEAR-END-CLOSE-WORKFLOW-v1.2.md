# Year End Close Workflow — v1.2.0

`Year End Close` is the only supported workflow for final financial-year P&L closure in this release.

## Preconditions

- Financial Year status is Open.
- Periods are contiguous and exactly cover the Financial Year.
- All periods except the final period have been closed through approved Financial Period Close documents.
- The final period remains Open and the posting date is its end date.
- Retained Earnings is an active Equity account.
- Finance Settings has a base currency.
- The trial balance through the year-end date balances.
- No Deferred Tax Posting Inbox items remain Pending Review or Approved.

## Approval and posting

The system snapshots the P&L ledger balances, full-year ledger fingerprint and automated controls. All nine review checklist items require completion, evidence references and reviewer notes. Approval must be independent of the preparer.

On submit, the source ledger and automated controls are rechecked. The closing journal is posted only through the Financial Posting Engine. Only after successful posting does the workflow close the final period and financial year.

The document is immutable after posting and cannot be cancelled. A controlled reopening and reversal workflow is required for corrections.
