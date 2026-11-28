# Velora Accounts - the financial engine (preview, v0.1)

`apps/velora_accounts` is a normal Velora app. Install it into any company (`velora company create ... --apps velora_accounts`, or `velora install-app velora_accounts`);
it seeds a starter chart of accounts (about 43 accounts, Nigeria-friendly IFRS groups), default accounts and the current fiscal year. Each company is its own set of books (database per company).

## The documents (Peachtree-style: no Payment Entry, no Journal Entry)

| Document | Purpose |
|---|---|
| **Receipt** | All money IN. *Customer* (applied to the customer's account) or *Other* (split across GL accounts). Method, reference, optional WHT suffered, gateway/bank fee, gateway + gateway reference. |
| **Payment** | All money OUT. *Vendor* (payee: Supplier or Employee) or *Other* (split across expense/asset lines). WHT deducted and credited to WHT payable. |
| **General Journal** | Every other posting, with a journal type: General, Adjusting, **Reversing** (an automatic reversal is created on the "Reverse On" date), Recurring, Opening Balance, Depreciation, Accrual, Prepayment, Intercompany, Bank Transfer, Year-End Closing. |
| **Journal Voucher** | A batch: every line (or every group of lines sharing a *Group* reference) becomes its **own General Journal**. Submit creates them all in one transaction (all-or-nothing); cancel cancels them all. Each line records the journal it created. |
| Account, Fiscal Year | Chart of accounts (tree) and fiscal years. |
| GL Entry | The ledger. Read-only for everyone. |

Cancelling any posted document is the "void", the ERPNext way: its entries are flagged cancelled (the exact opposite entries are recorded too, so any raw sum still nets to zero) and **disappear from the General Ledger, Trial Balance and statements**, with a "Show cancelled entries" option for audit. Nothing is deleted and no amount ever changes. To fix a mistake: **cancel, then Amend** (a pre-filled form; saved as `RCT-00001-1`, `-2` ...; linked both ways; once only), then submit. **Duplicate** copies any document into a new, unlinked draft.

## Rules the ledger enforces (whatever document posts)
* Double entry, exact `Decimal` to 2 places; **more precision is refused, never silently rounded**; a line is a debit *or* a credit, never negative or zero.
* Leaf, enabled accounts only. **Receivable/Payable accounts always carry a party** (Customer / Supplier or Employee); other accounts never do.
* The date must fall in an existing, **open fiscal year** and **after the books lock date**. The lock applies to everyone (an Accounts Manager can move it - an audited setting change). Cancelling a document in a locked or closed period is refused too.
* A voucher posts once. Ledger rows cannot be edited or deleted by anyone, including System Managers; the API cannot write them.
* **Cash and bank stay complete**: ordinary journals cannot touch Bank/Cash accounts (only Receipts, Payments, *Bank Transfer* between two of your own accounts, and *Opening Balance*). That keeps the cash book and bank reconciliation exact.
* Accounts with entries cannot change root type, group flag, account type or parent, and cannot be deleted. Fiscal years cannot be deleted or re-dated once used.
* Gateway references are unique per gateway: a replayed webhook cannot double-post (a cancelled receipt frees its reference).

Roles: *Accounts Manager* (everything, lock date, close years, defaults, cancel), *Accountant* (create/edit/submit, no cancel), *Accounts User* (read/export), *System Manager*.

## Reports
**Trial Balance** (opening, period, closing; debit/credit columns; hierarchical; Excel export in the QuickBooks style). Income/Expense openings restart each fiscal year; prior years' result not yet closed by a *Year-End Closing* journal is shown explicitly so the report always balances.

## Verified
Specific rules (parametrised), a **randomised invariant test** (150 random journals with random cancellations: the ledger always balances, every balance equals the sum of the non-cancelled journals, the trial balance always nets to zero), permissions per role, direct ledger-level tests (so the guarantee does not depend on any document), mutation checks (each rule deliberately broken is caught), SQLite and PostgreSQL, and an end-to-end run over HTTP on PostgreSQL (two roles, a Paystack-style receipt with WHT and fee, a replayed webhook rejected, Trial Balance exported to Excel and recalculated).

## Not built yet (next slices, in this order)
1. **Batch engine + Batch Bank Transactions, Expense Batch, Bank Transaction Processor** (one router: money out -> Payment, money in -> Receipt, no cash/bank -> General Journal), Excel import/export, statement import, coding rules, amortisation, bank-file/bulk payout. *The Journal Voucher above is the first batch.*
2. **Invoices + allocation** (Sales/Purchase Invoice, Receipts/Payments applied to invoices, deposits/advances, discounts), customer/supplier masters (party is free text today and is validated only for type).
3. **Payment gateway adapters** (Paystack, Flutterwave, Stripe, bank transfer): signature-checked, replay-safe webhooks that create Receipts; fees as expenses; bulk payouts; per-company API keys and outbound webhooks.
4. **Mobile layer** (installable app, card lists, quick-entry receipts, offline drafts).
5. Bank reconciliation studio, General Ledger / Balance Sheet / Income Statement / Cash Flow reports, recurring journals (needs the job queue), multi-currency (today: one currency per company), cost centers as a dimension, tax-code tables.
