# VeloraERP 2.106.0

Requires Velora >=1.19.0,<1.21.0.

- Advice for the common finance refusals: Finance Settings missing, no Financial Year or Period, closed period, backdating, missing exchange rate, depreciation not up to date, account restrictions (currency, group, frozen, cost centre, party), budget blocks, physical verification, workflow-controlled status and locked documents. Each says how to fix it and links to the screen.
- Exchange rates: a rate more than 7 days older than the document is a note, not a block; a foreign document with no rate (rate left at 0) is refused with a link to add one; a rate of 1 kept because none was found is a note.
- Access profiles for People & Access: Accountant, Finance Manager, Auditor (read only), Sales, Purchasing, Store and inventory, HR, Payroll, Projects, Support desk, Employee (self-service).
- Sample workflows for Purchase Receipt, Delivery Note, Sales Order, Purchase Order and Salary Slip now use the built-in Workflow State (no Customize Form). Stock Entry keeps its Entry Status. Still offered only; installing saves them switched off.
