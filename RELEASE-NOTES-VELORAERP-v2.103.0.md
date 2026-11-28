# VeloraERP 2.103.0 - Debt & Treasury

A new application area for borrowing: lenders, facilities, loans, repayments, interest, covenants, liquidity and currency risk, all posted to the ledger for you.

## What you can do
- **Financial Institution** (lender), **Financing Facility** (limit, pricing fixed or floating, repayment structure, security, covenants, accounts, withholding tax rule), approved through the normal workflow.
- **Financing Drawdown**: draw a loan on a facility. The system posts the bank receipt, the loan liability and any arrangement fee, builds the repayment schedule (annuity, equal principal, bullet or interest only, with grace period) and refuses a drawdown above the headroom or outside the availability dates.
- **Interest Accrual**: one document accrues interest for all loans to a date (Actual/365, Actual/360 or 30/360), posting the cost and the accrued liability.
- **Financing Repayment**: pay an instalment. Principal, interest and fees are split for you, accrued interest is cleared first, and **withholding tax on interest** is posted to the tax account and appears in the Tax Ledger and WHT All Sources.
- **Facility Amendment**: change the rate; floating loans are repriced and the unpaid instalments rebuilt. Cancelling the amendment restores them.
- **Covenant Test**: record a covenant result; the status is Compliant, Warning (inside the margin) or Breach.
- **Cancel** any of the above and balances, schedules and facility headroom are put back. Positions are recomputed from the submitted documents, so a cancellation can never leave them wrong.

## Where to find it
- **Debt & Treasury hub** in the sidebar, grouped into Lenders & Facilities, Loans & Drawdowns, Repayments & Interest, Covenants & Risk and Setup.
- **Treasury Centre** (`#/treasury-centre`): total and net debt, weighted rate and floating share, debt service for 30 and 90 days, rate-shock cost, the adviser's findings, maturity ladder, facility headroom bars, weekly cash runway, covenant status, lender mix and currency exposure.
- **12 reports** (Excel and PDF): Debt Portfolio, Debt Maturity Ladder, Debt Service Schedule, Loan Amortisation Schedule, Interest Expense and Accrual, Facility Utilisation and Headroom, Liquidity Forecast, FX Exposure and Sensitivity, Overdue Repayments, Covenant Monitor, Borrowing Cost by Lender, Security Register.
- **Debt & Treasury Advisor** (AI) and the rules-based **adviser** in the Treasury Centre: overdue and upcoming repayments, facilities nearly used or about to expire, breached or untested covenants, interest not accrued, lender concentration.
- A daily job refreshes positions and raises notifications.
- The existing **Treasury** workspace (bank processing, accruals, journals) is unchanged; the new area is named **Debt and Treasury** so the two are never confused.

## Honest limits
- The repayment schedule is contractual: it is rebuilt on a rate change but not for prepayments (a part-prepayment reduces principal; the remaining instalments are not re-amortised).
- No commitment fees, hedging instruments, trade finance or bonds issued.
- The liquidity forecast uses open customer invoices, supplier invoices and loan schedules; it does not forecast tax remittances or payroll.
- Tested on SQLite only. Not yet looked at in a browser.

Released together with framework 1.17.8.

## Also in this release
- **VeloraERP user manual rewritten for 2.103.0** (`docs/VELORAERP-USER-MANUAL-v2.103.0.html`): new sections Tax Management (rules, withholding tax from every source, income tax computation, deadlines, adviser, report library, print formats) and Debt and Treasury, a refreshed list of screens and hubs, the automatic tasks, and an honest "what is verified" section. The framework tutorial (`velora/static/tutorial.html`) has a new "What is new in 1.17.8" section.
- Workspace shortcuts may now point to the Tax Centre and Treasury Centre.

## Tested
- Framework 2,372 passed, 54 skipped; the one failure (`test_safe_http` DNS rebinding) needs outside DNS and fails in this sandbox only.
- ERP full run 603 passed, 1 skipped, 2 failed; both failures were mine (an account-type count; a missing posting-account filter on Financing Repayment) and are fixed and re-run green. Five Treasury tests (`tests/test_treasury.py`) cover the whole life cycle, every report and the daily job.
- Desk: 707 tests, type-check and production build clean. The built desk is included.
- SQLite only. PostgreSQL and a real browser have not been used.
