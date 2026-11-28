# VeloraERP 2.102.0 - Tax Report Library clean-up

- **60 duplicate or misleading report names removed** from the Tax Report Library. They were the same report under another label, or promised something the report did not do (for example "Penalty Computation" was the list of overdue obligations, and "Data Quality by Jurisdiction" was the overall scorecard). The library now has 125 distinct reports.
- **The catalogue lists only reports that run.** Entries that need data this system does not hold (transfer pricing, audit cases, document intelligence, integrations and so on) are no longer shown, so nothing in the list fails to open. The full specification file stays in the package for when a data source exists.
- **Fixed:** the Tax Data Quality Scorecard, Control Failures and Executive Tax Report failed with a division by zero on a book with no tax postings.
- **Tested:** every report runs on an empty book, with dates reversed, for a single day, over several years, and with tax type, jurisdiction and party filters.
- Tax Centre: the Report Library panel shows only reports that open.
- Released together with framework 1.17.7.
