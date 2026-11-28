# VeloraERP 2.98.0

## Accounting fix: Stock Received But Not Billed (GRNI)
**Cause found:** a Purchase Invoice created from a Purchase Receipt did not carry the receipt line's **UOM conversion factor** (or rate), so the invoice treated every line as factor 1. GRNI was then cleared for the wrong quantity (for a receipt in boxes of 12, 1/12 of the value), the rest was pushed to Purchase Price Variance, and **4091 Stock Received But Not Billed kept a balance** that never cleared. The invoice line now takes the factor and rate from the receipt line.
- Regression test: `test_grni_is_cleared_when_receipt_uses_a_uom_conversion_factor`.
- Checked and found correct: plain full invoicing, awkward decimals, foreign currency, line discounts, invoice rate different from receipt rate (variance goes to price variance), partial invoicing (balance equals exactly the uninvoiced value, then clears with the second invoice).
- **Existing data is not corrected automatically.** Invoices already posted with a wrong factor keep their entries. Cancel and amend them (cancel then amend is the supported route) and the corrected entries post.
- A rounding edge case still exists elsewhere: when a posting's base-currency lines differ by 0.01 the engine blocks posting rather than adjusting. This release does not change that rule.

## Preview Entry
- New **Preview Entry** button on submittable Finance documents. A submitted document shows the entries actually posted (read from the ledger); a draft invoice or return shows what it will post, built by the same posting adapter and checked for balance. Other drafts say their entries are created on submit; nothing is guessed.
- Cost-of-sales and inventory entries for stock items are created on submit, so a draft Sales Invoice preview does not list them.

## Batch picker, warehouse, email
- See Velora 1.17.0 notes. `Inventory`: `finance/inventory/batch_picker.py`, `/api/stock/batches`.

## Other
- Package version declared consistently (`__init__` and `pyproject` both 2.98.0).
