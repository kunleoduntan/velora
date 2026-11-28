# Tax Management: review and integration (ERP 2.99.0)

## What was received
`velora_tax_management` 0.1.0 is a standalone foundation: about 250 lines (rule model, calculator, WHT, ledger and return status helpers, report-catalogue loader) and a 460-report catalogue. Its own notes say it has no persistence, permissions, GL posting, workflow or report execution. Earlier uploads were an extract of the ERP's own tax files and a report-specification package; neither is used.

## Defects found in the foundation, and what was done
| # | Finding | Action |
|---|---|---|
| 1 | Inclusive tax: taxable amount was rounded from the unrounded tax, so taxable + tax could differ from the gross by 0.01 | Taxable = gross less the rounded tax; always reconciles (tested on edge values) |
| 2 | Credit notes: tiered rules returned zero tax on a negative base, percentage rules gave negative tax | Every method now returns a negative tax of equal size for a negative base |
| 3 | Tiered bands silently taxed any excess at the last band's rate; bands were not validated | Explicit contiguous bands, last one open-ended, rates 0-100, tiered rules cannot be inclusive |
| 4 | Rounding fixed at 2 places | Rounding places are a rule setting (0-8) |
| 5 | A fixed tax was charged on a zero base | Not applied to a zero base |
| 6 | Rates and recoverability not range-checked | Validated 0-100 |
| 7 | Rule ambiguity only detected on identical specificity and start date | Any two equally specific rules in force are rejected; overlapping effective periods for the same code, jurisdiction and category are refused when the rule is saved |
| 8 | "Reverse entry" only set a field and created no reversing entry; "post" took any GL reference string | Not carried over. The ledger is read from the GL itself, where reversals are real entries |
| 9 | Report catalogue: every one of the 460 entries carries a `company` filter, and the loader logic that strips CSV is redundant | `company` removed (this ERP has no company field), CSV removed, stable ids added, status marked honestly |
| 10 | Catalogue: all 460 entries have identical filters and features, 17 report names repeat across domains | Kept as the specification; ids include the domain |

## Integration decisions
- **Payroll tax is untouched.** Payroll Tax Rule, Jurisdiction, Band, Employee Tax Profile, Refund Review, Deferred Tax and `tax_engine.py` are not modified or read by the new code.
- **One source of truth.** The GL already stores every posted tax line (code, rate, taxable amount, tax amount). The Tax Ledger is read from it, so books and returns cannot disagree and cancelled documents net out. No second ledger was created.
- **Standardisation.** An invoice line whose Tax Code names an approved Tax Rule takes its rate (and tax account when empty) from that rule. *Tax Settings > Invoice tax codes must be approved Tax Rules* makes this mandatory for taxed lines. Off by default so existing data keeps working.
- **Approvals through the GUI workflow.** Tax Rule and Tax Return use the same approval status, fingerprint and immutability pattern as payroll tax rules. Changes to an approved rule go by cancel and amend.
- **Returns.** Built from the ledger by tax type, jurisdiction and period. Submission is blocked if the ledger moved after calculation. Filing records a reference; the authority outcome is recorded afterwards; the linked obligation follows.
- **Performance.** Rules are resolved once per invoice (one query pass per date), the ledger is a single joined, date-bounded query, and returns aggregate in memory over that result.

## Not built (stated plainly)
- Withholding tax is calculated (calculator and API) but not posted on payments or certificates; the ERP has no WHT posting today.
- Recoverability is applied in the return. Invoice posting still books all input tax to the input-tax account.
- Fixed, tiered and tax-inclusive rules cannot be placed on invoice lines (refused with a message); they are available to the calculator.
- Of the 460 catalogue reports, 5 are executable (VAT Transaction, Output VAT and Input VAT registers via Tax Ledger; VAT Return Summary; Compliance Calendar). The other 455 remain specifications.
- No Nigerian rates, categories or filing calendars are seeded: enter statutory values as approved Tax Rules.
- No custom desk screens beyond the hub, forms, lists and reports. Not browser-tested.
- Tests use SQLite only.
