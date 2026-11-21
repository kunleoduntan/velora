# Tax and Year-End Governance — v1.1.0

## Tax engine

Velora's payroll tax engine is jurisdiction-neutral. It calculates tax only from approved, effective-dated rules and bands configured by the implementing organisation. No Nigerian, Ghanaian, UK, or other statutory rates are hard-coded in the engine.

Tax band schedules must begin at zero, be contiguous and non-overlapping, and end with one open-ended band. Band sequences must be unique. Rounding precision is restricted to 0–8 decimal places. Tax jurisdiction country codes are normalised to uppercase two-character ISO codes, and tax-year start dates are checked against the selected month.

A given employee cannot have overlapping effective-dated tax profiles for the same jurisdiction. A tax rule code cannot have overlapping effective-dated versions within the same jurisdiction. New rules/profiles remain subject to the existing independent approval and immutable-approved-record controls.

## Cumulative tax adjustment

`calculate_ytd_tax_adjustment` is a deterministic calculation primitive. The caller supplies year-to-date taxable income, prior tax withheld, the number of periods remaining after the current period, periods per year, the approved tax bands and annual relief. The calculation annualises the observed average taxable income and determines the cumulative target withholding.

A negative adjustment is explicitly flagged for refund/credit review. It is not silently converted into a negative deduction, refund, employee receivable or journal. The function is not a statutory PAYE filing and must be integrated into the employer's approved payroll policy before production use.

## Year-end closing proposal

`build_year_end_closing_proposal` accepts the approved trial-balance balances for income and expense accounts using the debit-minus-credit sign convention. It reverses the profit and loss account balances and transfers the resulting net profit or loss to the configured retained earnings account. It validates account uniqueness, account types, amounts, currency precision, posting date and required financial-year context.

The result is **Draft Proposal** only. It has a deterministic fingerprint, balanced debit/credit totals, an independent-approval requirement and an explicit requirement to use the central Financial Posting Engine. The function does not create a document, mutate a ledger, submit a journal or close a financial year. The application workflow must persist the reviewed proposal, revalidate its fingerprint and source balances, obtain independent approval, and post through the Financial Posting Engine before closing the financial year.

## Production controls

- Configure statutory rates, reliefs, thresholds, caps, tax-year dates and effective dates from verified local legal sources.
- Have local tax and payroll specialists approve every tax rule before use.
- Reconcile payroll tax deductions and employer contributions to their statutory liability accounts before remittance.
- Reconcile statutory remittances to bank evidence and authority receipts.
- Reconcile all income and expense accounts to the final approved trial balance before generating a year-end proposal.
- Do not post the proposal until it has passed independent review and posting-engine validation.
- Retain tax rule versions, employee tax profile versions, calculation snapshots, approvals, remittance evidence and year-end proposal fingerprints for audit.

This release provides reusable calculation and validation controls. It does not certify legal compliance, connect to a tax authority, submit returns, execute payments, or autonomously post year-end journals.
