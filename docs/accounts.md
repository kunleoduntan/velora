# Velora Accounts - the financial engine (`apps/velora_accounts`, v0.3)

Install: `velora --company COMP-001 install-app velora_accounts` (a starter chart of accounts, defaults and the current fiscal year are created).
Needs `openpyxl`. Works on SQLite and PostgreSQL; every company has its own books (its own database).

## The model: Receipts, Payments, General Journal - no Payment Entry, no Journal Entry
| Document | Use |
|---|---|
| **Receipt** | all money coming in: from a customer (settles their account) or "Other" (split over accounts); WHT suffered; gateway/bank fee; gateway reference (a retried webhook can never post twice) |
| **Payment** | all money going out: to a supplier/employee (settles their account) or "Other"; WHT deducted; gateway reference guard |
| **General Journal** | every other posting, with a journal type: General, Adjusting, Reversing (auto-reverses on a date), Recurring, Opening Balance, Depreciation, Accrual, Prepayment, Intercompany, **Bank Transfer**, Year-End Closing |
| **Journal Voucher** | a batch of lines; **each line (or group of lines) becomes its own General Journal**, all in one transaction |
| **Batch Bank Transaction**, **Expense Batch**, **Bank Transaction Processor** | batches whose rows become Receipts, Payments or Bank Transfers (below) |

Rules enforced for *every* voucher by `ledger.py`: debits = credits exactly (Decimal, 2 places; extra precision is refused, never rounded); a line is a debit **or** a credit;
only leaf, enabled accounts; Receivable/Payable accounts always carry a party and others never do; the date must be in an existing **open** fiscal year and after the **books lock date**;
a voucher posts once; entries are never edited or deleted - cancelling posts an exact mirror. Journals cannot touch bank/cash accounts (except Bank Transfer and Opening Balance), so the cash book is always complete.

## The batch engine (`batch.py`)
Each row has *Money In* or *Money Out* (never both) and the router decides:

| Row | Creates |
|---|---|
| Money in, customer named, no account | Customer **Receipt** |
| Money in, an account | Other **Receipt** |
| Money out, supplier/employee named, no account | Vendor **Payment** |
| Money out, an account | Other **Payment** |
| Type = Transfer (Account = the other bank/cash account) | General Journal of type **Bank Transfer** |

* **Pre-flight on save**: every row is built as the real voucher and validated; *all* problems are reported together, per row (capped at 25 shown). The generated voucher's own line numbers are hidden: you only see your row numbers.
* **All-or-nothing on submit**: every voucher is created in one transaction; a failure part-way (even after earlier rows were created and posted) rolls everything back and the same batch can be resubmitted.
* **Traceable**: each row records `created_type`/`created_ref`; vouchers record `source_type`/`source_ref`. Cancelling a batch cancels its posted vouchers (flagged cancelled and hidden from reports, never deleted) and deletes drafts.
* **Draft or Submitted** (`create_as`): Draft vouchers wait for approval in Receipts/Payments; Submitted post to the ledger when the batch is submitted. A submitted batch cannot change it.
* **Duplicates**: a row whose bank, date, amount and reference match an existing Receipt/Payment (or an earlier row) is refused - re-importing a statement is safe. "Allow Duplicate" overrides. Cancelled vouchers don't count.
* **WHT %** (gross basis) and **Fee** (receipts) flow through to the vouchers.
* **Expense Batch**: only money out is posted unless "Also post money-in rows" is ticked (avoids double-booking petty-cash top-ups).
* **Bank Transaction Processor**: rows must fall inside the statement period; with opening and closing balances entered, the rows must **add up to the statement** (measured on what actually hits the bank, after WHT/fees) or saving is refused with the exact difference.
* **Amortise** (Payment rows): the payment is parked in *Prepayments*; a schedule (one row per month, month-end dates, equal shares rounded down with the remainder on the last month) is created. `amortisation.post_due(as_of)` - run monthly - posts a *Prepayment* journal for each due month. Safe to re-run; nothing is recognised until the payment itself is posted; locked/closed months are reported, not fatal, and catch up later; a cancelled payment cancels its schedule.

### Excel / CSV (`batch_io.py`)
`template_bytes()` (Transactions + Instructions sheets), `export_bytes(batch)`, `import_rows(batch, bytes, filename, replace=False)`. Columns are matched **by heading** in any order, and a bank's own headings work
(*Value Date, Description, Withdrawal/Deposit or Debit/Credit, Transaction Reference*). Bad rows are reported individually (with their Excel row number) while good rows still import; CSV (with Excel's BOM) works;
dates as `YYYY-MM-DD` or `DD/MM/YYYY`; formula-looking text is stored as text (no formula injection); files over 5 MB or 5,000 rows are refused.

## Tested
~110 tests (accounts + batches) on SQLite and PostgreSQL, including a randomised invariant (hundreds of vouchers: the books always balance, and cancelling everything returns every account to zero),
and mutation checks on the guarantees above (a mutation that swallowed a failing row survived at first - which is why there is now a test that fails *during* creation).

## Customers, suppliers, invoices (v0.3)
* **Customer / Supplier masters** (TIN, contacts, payment terms in days, status Active/Blocked; suppliers also carry bank details for the payouts to come; customers a credit limit).
  **Strict parties** (default ON): nothing can be posted to a customer/supplier that is not in the master - a typo can never create a ghost account. It is checked in the ledger itself, so Receipts, Payments, journals, Journal Vouchers and batches all obey it (batches report it per row).
  A manager can turn it off (e.g. while loading legacy balances). Employees have no master here (HR owns them), so they are not checked.
* **Tax Codes**: VAT Output / VAT Input with a rate and a Tax account. Seeded: 7.5% and 0% each way (editable - check them against current law).
* **Sales Invoice / Purchase Invoice**: items with an account and optional tax code; VAT rounds per line to the kobo; due date from the party's payment terms; a purchase invoice refuses a **duplicate supplier invoice number** (per supplier).
  Posting: sales Dr Receivable / Cr Income + Output VAT; purchase Dr Expense or Asset + Input VAT / Cr Payable. Cash, receivable, payable and tax accounts cannot be used as item accounts. Blocked parties cannot be invoiced.
  A submitted invoice cannot be edited; one that has been (part-)settled cannot be cancelled until its receipts/payments are.
* **Per-invoice settlement**: a Customer Receipt / Vendor Payment can settle one or many invoices (`Settle Invoices` table), with an optional **settlement discount** per invoice (posted to *Discount Allowed* / *Discount Received*).
  WHT suffered/deducted and gateway fees still work, and the invoice is settled at its gross value. Money not applied to an invoice stays **on the party's account** as a credit (shown as a credit balance) - nothing is lost or guessed.
  Statuses: Unpaid, Partly Paid, Paid, Cancelled. The outstanding amount is changed only under a database row lock; on PostgreSQL, 8 simultaneous receipts for one invoice let exactly one win (tested; removing the lock makes the test fail).
* **Reports**: **General Ledger** (any account and/or customer/supplier, opening balance, running balance (cancelled entries are hidden unless you tick "Show cancelled entries") - so it is also a customer/supplier statement), **Aged Receivables**, **Aged Payables**
  (buckets by days overdue from the due date, using each invoice's *current* outstanding).
* **Upgrading from v0.2**: `velora upgrade` adds the new tables and runs a data patch that creates the Discount accounts, the new default accounts (incl. Prepayments), the VAT codes, and **a master record for every customer/supplier that already has postings** (so strict parties never locks you out of an existing customer). Verified end to end: a v0.2.0 company with real postings upgraded to v0.3.0 with its books untouched.

### Fixed in the framework along the way
* Report **totals were summed as floats** (a total could show `0.30000000000000004`; a trial balance's debits and credits differed by 1e-11). They are now exact decimals.
* The **Excel export silently dropped `Decimal` numbers** (blank cells) - any report returning exact money would have exported without its figures. Fixed; both have regression tests that fail without the fix.

## Not built yet (honest list)
* **Credit notes / returns**, applying an existing on-account credit to a *later* invoice, invoice-level multi-currency, recurring invoices, printable invoice formats, and aged reports as of a past date (they use today's outstanding).
* **Payment gateways** (Paystack/Flutterwave/Stripe adapters, webhooks, settlement matching) and the **bank payment file / bulk payout** (Zenith ISO 20022, SFTP). Receipts/Payments already carry the gateway reference guard these will use.
* **Bank reconciliation**, General Ledger / statement reports (only the Trial Balance exists), multi-currency, cost-centre reporting.
* **UI wiring**: the Python API exists (`import_rows`, `export_bytes`, `post_due`), but there are no Desk buttons/REST endpoints for them yet, and no scheduler to run `post_due` monthly. The mobile layer is still to do.
