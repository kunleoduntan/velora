# Finance Payroll and Employee Finance — v0.96.0

## Ownership model
Payroll, salary structures, payroll runs, salary slips, payroll payments, employee loans, employee advances and their financial settlements are Finance-owned records. HR consumes employee identity, employment, attendance, leave, approved changes and payroll input interfaces. Organisation administrators can grant HR selected preparation/review rights without granting unrestricted salary, bank, posting or payment access.

## Payroll design
Salary Components are reusable rules with ordered calculation sequence, component category, calculation type, effective input, attendance proration and accounting mapping. Salary Structures combine these rules; Salary Structure Assignments are effective-dated and employee-specific. Payroll Runs snapshot the calculation and require independent approval. Submission creates employee Salary Slips and posts the payroll accrual through the central Financial Posting Engine. Payroll Payment separately settles the employee-specific net salary liability.

The calculation engine supports fixed values, percentages of base salary, percentages of previously calculated gross earnings, arithmetic formulas and explicit inputs. Formulas use a restricted arithmetic AST; no Python execution or arbitrary function calls are permitted. Formula variables include base_salary, gross, net, days_worked, days_in_period, overtime_hours and previously calculated component codes.

## Accounting treatment
- Earnings: debit configured expense accounts.
- Employee statutory and other deductions: credit configured liability/settlement accounts.
- Employee loan and advance recoveries: credit the employee receivable control account with Employee party tracking.
- Net pay: credit the configured employee-party-tracked salary payable account.
- Employer contributions: debit configured expense accounts and credit configured liability accounts.
- Salary payment: debit employee salary payable and credit bank/cash through a separate approved Payroll Payment.

No payroll document writes Account Ledger Record directly. All postings use `post_financial_transaction`.

## Employee loans and advances
Employee Loan supports approval, reducing-balance or equal-principal/equal-instalment schedule generation, disbursement and separate repayments. Employee Advance supports approval, disbursement, expense-evidence settlement and cash refund settlement. Payroll deduction components may be mapped to employee loan or advance receivable accounts; the deduction must be included in payroll inputs and must not exceed gross pay.

## Scope and controls
This release provides a configurable payroll calculation core and finance accounting lifecycle. It does not claim a statutory country pack. PAYE, pension, social insurance, withholding, year-end filing and country-specific statutory calculations must be implemented as separately versioned localisation rules after authoritative jurisdictional requirements are configured and reviewed. Attendance, leave, work schedules, recruitment and employee lifecycle remain HR-owned upstream systems. Payroll requires valid employee, salary assignment, approved salary structure, component accounts, periods, currency and approval segregation.
