# VeloraERP v2.91.0 — Gross Pay on the Employee

Requires Velora Framework `>=1.15.0,<1.16.0`.

## Gross Pay
- **Employee > Employment > Compensation > Gross Pay**: the total gross pay agreed for the employee, maintained by HR/Payroll. It is a permission-level 1 field: only System Manager, HR Manager and Payroll Manager can change it; Finance Manager, Payroll Officer, Employee Finance Officer and Auditor can read it. Other roles (including the employee and department managers) do not see it. The Role & Field Permissions page can change this per company.
- **Salary Structure Assignment > Gross Pay (reference)**: a read-only copy fetched from the Employee while the assignment is a draft. It sits beside Base Salary and is **never used to calculate payroll**, so allowances are not counted twice. Payroll still calculates from Base Salary and the Salary Structure components.
- Check on save: Base Salary cannot be more than the employee's Gross Pay (when a Gross Pay is set).
- The approval fingerprint does not include Gross Pay, so a change on the Employee does not invalidate approved assignments.

## From 2.90.0
- Employee Name is built from First, Middle and Last Name.
- Account Ledger and Trial Balance accept an inclusive account range; customer, supplier and employee ledgers and statements pass it through.
- No Finance or HR workflow templates are installed; companies design their own in Settings > Workflows.

## Housekeeping
- Removed the old versioned release notes, validation files and start-here files that were still sitting in the VeloraERP and ProjectOne folders, and two stale files in the framework package.
- Not changed: number/currency display format per company (see the delivery message).
