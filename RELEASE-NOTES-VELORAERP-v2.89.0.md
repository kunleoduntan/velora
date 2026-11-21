# VeloraERP 2.89.0 (needs Velora 1.13.x)

Finishes the cancel redesign of 2.88: **every** document type can now be cancelled, and the old reversal machinery is gone.

## Cancel works for everything
- **Fixed assets** – depreciation run, revaluation, impairment, disposal, transfer, component adjustment, CGU impairment and its reversal, lease modification and termination restore the asset (cost, depreciation, carrying amount, status, components, book balances, lease schedule) and remove their history entries. Purchases and leases remove the assets they created. A later event on the same asset refuses the cancel and names it (newest first).
- **Payroll** – payroll run (its slips are cancelled with it; loan and advance recoveries, one-time inputs and PAYE credit reviews go back), payroll payment (slips back to unpaid), employee loan and advance (while untouched), loan repayment, advance settlement, and the payroll masters (inputs, structures, assignments, loan types, tax profiles and rules).
- **Investments** – Investment and Investment Transaction use the normal Cancel (newest transaction first). The Reverse routes and menu are gone.
- **Period and year end** – Financial Period Close and Year End Close reopen the period / year and remove the closing journal. Deferred tax posting inbox, inventory valuation closing, budgets, budget adjustments, report publication and recognition schedules can be cancelled too.
- How: a **Posting Restore Point** (internal, hidden) saves the records a document changes just before it is submitted; cancel puts them back and refuses if any of those values were changed by a later document.
- Documents show status **Cancelled** wherever they have a status list.

## Removed
- The **Reversal** posting event, `reverse_financial_posting`, `reversal_of` on batches / lines / ledger rows, the `reversal_batch`, `reversed_on`, `reversal_reason` fields on Receipt and Payment, the Investment `reversal_batch` fields, the ledger "reversal pair" bank-matching step and the GL Review "reversal value" figure.
- Upgrade patch `v2_89.convert_legacy_reversals`: an old reversal pair (reversed Receipt, Payment, Investment ...) is deleted together with its original posting and the document is marked Cancelled (a Posting Cancellation Log records it). An Accrual's automatic reversal stays, as an ordinary Adjustment posting.
- The Accrual automatic reversal is kept deliberately: it is an accounting convention (accrue now, reverse next period), now a normal dated posting that is cancelled with the accrual.

## Report consistency
- Ledger-based reports are right by construction (cancelled postings no longer exist). Registers already read submitted documents only.
- Tax profile and tax rule overlap checks, group budget children and the customer portal complaint link now ignore cancelled documents.

## Honest limits
- Documents submitted **before** 2.89 that change other records (assets, payroll, loans, period/year close) have no restore point and refuse the cancel with a clear message.
- Stock: issues already costed are not re-costed after an earlier receipt is cancelled (as in 2.88).
- Removed code nothing used: the standalone reporting library (`finance/reporting`), allocation/settlement/party-adjustment/subledger libraries, recruitment services and the old naming-series helper, with the tests that only exercised them. Five report-approval authority names that went with them are gone from Finance Settings > Approvals.
- Tested on SQLite and on PostgreSQL 16 (see the delivery message for results).

- Desk: sidebar restyled (dark brand bar, line icons, chevron groups open only on the current page, filled active pill, "Configure Features" at the bottom). Form toolbar: create-from-another-document actions now sit in one "Create" menu next to Duplicate, Amend and Cancel.
- Removed unused doctypes Financial Reporting Schedule, Financial Reporting Review (+ item table), Cash Flow Account Mapping, Financial Disclosure Note, and the unused FinancialReportingDashboard screen. Existing sites keep their (empty) tables; they are not dropped.
