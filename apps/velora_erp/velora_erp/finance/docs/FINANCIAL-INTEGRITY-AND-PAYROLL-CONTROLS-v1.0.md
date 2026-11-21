# Financial Integrity and Payroll Controls — v1.0.0

## Statement and note control chain

Financial statement lines and disclosure notes must be supported by explicit account and source mappings. The reporting layer compares schedules with ledger snapshots and statement values. Missing account mappings, missing source references, duplicate mappings, invalid values and differences beyond tolerance are surfaced as publication blockers. Reconciliation is read-only and never generates an adjustment journal.

## PPE note calculation

Closing cost = opening cost + additions - disposals + transfers.

Closing accumulated depreciation = opening accumulated depreciation + depreciation - accumulated depreciation on disposals.

Closing accumulated impairment = opening accumulated impairment + impairment charges - reversals - accumulated impairment on disposals.

Closing carrying amount = closing cost - closing accumulated depreciation - closing accumulated impairment.

Current and comparative schedules are independently checked.

## Payroll statutory contribution mapping

Employer contributions use an expense debit and statutory payable liability credit. The payable account must be a Liability account. An optional statutory scheme code is retained on the payroll calculation snapshot. Employee statutory deductions remain separate from employer contributions in the statutory register.

## Payroll settlement control

For each Salary Slip:

Outstanding salary payable = net pay - recorded paid amount.

Posted Payroll Payment lines are aggregated by Salary Slip and compared with the recorded paid amount. Any difference, overpayment or inconsistent outstanding balance is an exception. Payment submission also validates the live Salary Slip balance and the approved bank settlement instructions.

## Governance

All source corrections remain controlled through the relevant document workflow and central Financial Posting Engine. Posted payroll and ledger history is not rewritten by these reconciliation processes.
