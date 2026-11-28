# VeloraERP 2.97.0
## Waybill from the documents that already exist
A Waybill can now be created from a **Sales Invoice** or a **Sales Order** as well as a Delivery Note, with partial consignments (it only offers the quantity not yet on a waybill). A Delivery Note is no longer required to create one; invoicing a waybill that has no Delivery Note says so clearly.

## Group consolidation (new)
Companies keep separate databases, so consolidation is its own, authorised step. Define a **Consolidation Group** (companies, ownership %, Full or Proportionate, the reporting currency, elimination rules, optional account mapping), then use the **Consolidation Centre** (Finance hub): choose the group and period, press Consolidate.
- Each member is read **as you, with the roles you hold in that company**. A company you cannot enter is left out and reported; nothing is read on the strength of a role held elsewhere.
- Translation: assets and liabilities at the closing rate, income and expenses at the average rate, equity at the equity rate, earlier unclosed results at the opening rate. Rates come from what you type on the group or that company's own exchange-rate table. **A missing rate stops that company; nothing is guessed.** What translation leaves behind is shown as a *currency translation reserve*.
- Accounts line up by account code (or name); the account mapping table handles the exceptions. A code that is an asset in one company and a liability in another is an error.
- Elimination rules (intercompany balances, income and expense, investment against capital, dividends): every entry balances on its own; when the two sides differ the matching part is eliminated and **the difference is reported, not forced away**.
- Output: worksheet (a column per company, eliminations, consolidated), income statement, balance sheet, eliminations, checks; each exports to Excel. A run can be saved (Consolidation Run, not editable afterwards).
- A plain banner says whether the result can be relied on.

**Not calculated** (and the Checks tab says so): goodwill and fair-value adjustments at acquisition, the equity method, deferred tax on eliminations, and a separate rate per historical equity movement. The non-controlling share is a share of the company's net assets and profit before eliminations.
