# Cumulative PAYE and Refund/Credit Review — v1.2.0

## Cumulative calculation

For an employee and approved tax rule, Payroll Run derives prior YTD taxable income and PAYE withheld from submitted Salary Slips in the tax year. It adds current taxable earnings, projects annual liability using the approved rule, calculates the cumulative target and subtracts actual prior withholding.

Only posted Salary Slips count. Overlapping periods, duplicate posted periods, periods crossing the configured tax-year boundary, changes in pay frequency and annual period exhaustion are rejected. A tax component configured for cumulative YTD must map to a Liability account.

## Negative adjustment

A negative current-period adjustment is not posted as a negative deduction. The system creates a Tax Refund Credit Review in Pending Review status. The Payroll Run cannot be submitted until the review is independently approved.

After approval, the amount increases the employee's net salary payable and a debit to the PAYE liability account is included in the payroll posting. Both entries are posted through the Financial Posting Engine. If a later payroll recalculation changes the YTD source, the existing approval is automatically invalidated and the review returns to Pending Review. The manager must approve the refreshed amount again. Once applied, the review is immutable.

This is a calculation and control mechanism, not a statutory tax determination. Tax bands, reliefs, tax-year dates and legal treatment must be validated for each jurisdiction.
