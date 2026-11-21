# Employee Loan Recovery Protection — v0.98.0

## Policy hierarchy

Finance Settings defines the company-wide maximum combined loan deduction as a percentage of net pay before loan recoveries. The default is 30%; administrators must confirm the applicable company policy and local legal requirements before production use. A value of zero disables the percentage ceiling, but the configured minimum net pay floor continues to apply.

Each Employee Loan Type may define a stricter maximum percentage, a recovery priority, a recovery allocation method and whether partial recovery is allowed. A type-level percentage of zero inherits the company-wide percentage. Type-level caps never increase the company-wide cap.

## Net-pay basis

The cap basis is net pay before loan principal and interest recovery, after ordinary employee deductions and configured advance recoveries. Employer contributions are not employee deductions and are excluded. The maximum recoverable amount is the lower of:

- net pay before loan recovery multiplied by the company-wide percentage; and
- net pay before loan recovery less the configured minimum net pay floor.

The cap applies once to the employee's combined principal and interest recovery across all running loans. It is not multiplied by the number of loans or loan types.

## Allocation

Due amounts are grouped by loan type. Loan type priority is applied first (lower numeric value is earlier). Each type's optional percentage cap is then applied, subject to the remaining company-wide capacity. Within a type, the selected allocation method applies: oldest due first, highest interest first, lowest balance first, or pro rata. Interest is allocated before principal within an individual loan allocation. Every allocation retains the originating employee loan reference and is later applied to its repayment schedule.

If partial recovery is disabled globally or for a loan type, that type is skipped when the full due amount cannot be recovered within its available capacity. The unpaid schedule remains outstanding and will be reconsidered in a later payroll run; no amount is written off or silently removed.

## Lifecycle and controls

Payroll calculation reads loan schedules and produces a proposed allocation snapshot. It does not mutate loan schedules or outstanding balances. Recalculation discards the prior unposted snapshot and rebuilds it from current due schedules. Independent payroll approval freezes the calculation fingerprint. Only successful payroll posting commits each principal and interest allocation, updates schedule lines and reduces loan principal. Posting is idempotent through the Payroll Run's existing financial posting key.

The Payroll Run Employee row retains the protection summary and detailed loan allocation snapshot for review and audit. A minimum net-pay check is repeated against the final payroll result before posting.

## Operational notes

- Finance Settings maximum combined loan deduction: default 30% of net pay before loan recovery.
- Minimum net pay after loan deductions: default zero; configure a non-zero amount when policy requires it.
- Loan Type percentage: zero inherits the global setting; otherwise it may impose a stricter cap.
- Loan Type recovery priority: lower number is recovered first.
- Partial recovery: company and loan type controls must both permit it.
- Unrecovered amounts remain on their original schedules; they are not journalled, waived or written off automatically.
- Validate statutory and contractual deduction restrictions for each jurisdiction before enabling payroll production.


## Salary Component account mapping

Ordinary Salary Components use one primary Account field. Earning components debit the mapped expense account. Employee deductions, principal recoveries, interest recoveries and advance recoveries credit the mapped settlement/liability/receivable account. The net salary payable account remains configured at Payroll Run/company level. Legacy debit/credit fields remain hidden for compatibility. Employer Contribution is currently a two-sided special case because the expense and statutory payable accounts are distinct; the legacy pair remains available for that component type pending a dedicated statutory contribution mapping.
