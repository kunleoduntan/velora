"""Integration contracts. Adapters must call shared Velora services, never write GL records."""
INTEGRATION_CONTRACTS = {
 "accounting": {"direction":"read_and_reference", "source_of_truth":"Velora Accounting", "posting":"Never post directly; use shared Accounting posting service through approved source adapters."},
 "hrms": {"direction":"read_and_reference", "source_of_truth":"Velora HRMS", "objects":["Employee","Department","Designation","Leave Application","Shift Assignment"]},
 "payroll": {"direction":"read_and_reference", "source_of_truth":"Velora Payroll", "objects":["approved payroll costing allocations"]},
 "procurement": {"direction":"read_and_reference", "source_of_truth":"Velora Procurement", "objects":["Purchase Requisition","Purchase Order","Purchase Receipt","Purchase Invoice"]},
 "inventory": {"direction":"read_and_reference", "source_of_truth":"Velora Inventory", "objects":["Stock Entry","Inventory Issue","Item"]},
 "fixed_assets": {"direction":"read_and_reference", "source_of_truth":"Velora Fixed Assets", "objects":["Asset","Asset Movement","Depreciation Schedule"]},
 "crm_sales": {"direction":"read_and_reference", "source_of_truth":"Velora CRM and Sales", "objects":["Customer","Opportunity","Sales Order","Sales Invoice"]}
}
