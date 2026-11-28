# VeloraERP 2.101.0 - Tax Report Library

## What is new
- **Tax Report Library** (Tax Management > Reports): one report that runs 185 tax reports. Choose the report, the period and, if you want, a tax type, jurisdiction or party; the columns follow the report. The period defaults to the year to date. Excel and PDF export only.
- Covered areas: VAT and GST analysis (by rate, category, customer, supplier, item, account, jurisdiction; recoverability; payable and receivable; credit balance; adjustments; exceptions), withholding tax (certificates, exceptions, credit utilisation, remittance reconciliation), income tax (taxable income, losses, minimum tax, provision, capital allowances, effective rate, rate and profit sensitivity), deferred tax (differences, tax bases, assets and liabilities, recognition, movement), compliance (obligations, returns, versions, rejections, review queue, scorecards, work queues), liabilities, payments and credits (aging, cash-flow forecast, authority statement), analytics (month, quarter and year comparisons, trend, forecast, anomaly detection), data quality (scorecard, rules, accounts, registrations, duplicates, trend), change and approval history with segregation-of-duties conflicts, and an Executive Tax Report.
- The Tax Centre shows the Report Library by area, with search. Reports that run link straight to the report with the choice made.
- The tax report catalogue now reports status honestly: 203 of the 460 catalogued reports run (the 29 existing reports plus the library); the other 257 are specifications only.

## What does not run, and why
Transfer pricing and international tax, audit and dispute cases, document intelligence, integrations and migration, tax budgets, incentives, assessments and refund applications need data this system does not hold. They stay in the catalogue marked "specification" and cannot be opened. Nothing is faked.

## Notes
- Rates are never built in. VAT, WHT and income tax reports read the approved Tax Rules.
- Reports read the general ledger and tax documents; they change nothing.
- Released together with framework 1.17.6.
