# Integration Contracts

- **Accounting:** ProjectOne supplies project/WBS/cost-category dimensions to approved source adapters. Accounting owns journals and the General Ledger. No ProjectOne GL writes.
- **HRMS:** Employee, department, designation, skills, leave and availability are read from HRMS; ProjectOne does not create a competing employee master.
- **Payroll:** Approved timesheet and allocation references may support labour costing; payroll remains authoritative for payroll calculations and posting.
- **Procurement:** Purchase requisitions, POs, receipts and invoices remain in Procurement/Accounting. ProjectOne mirrors open commitments with source identifiers and reconciliation state.
- **Inventory:** Project material issues are sourced from Inventory transactions. ProjectOne must not decrement stock.
- **Fixed Assets:** Asset acquisition, depreciation and movements remain in Fixed Assets/Accounting; ProjectOne may track project assignment and handover references.
- **CRM/Sales:** Customers, opportunities, sales orders and invoices remain in CRM/Sales/Accounting. ProjectOne may manage delivery and billing milestones.
