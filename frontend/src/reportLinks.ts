/** Reports a record can open already filtered to itself (shown as a "Reports" menu on the form). */
export interface ReportLink { report: string; label: string; filter: string }

export const REPORT_LINKS: Record<string, ReportLink[]> = {
  Account: [{ report: "Account Ledger", label: "Account Ledger", filter: "account" }],
  "Inventory Item": [
    { report: "Stock Ledger", label: "Stock Ledger", filter: "item_code" },
    { report: "Stock Balance", label: "Stock Balance", filter: "item_code" },
    { report: "Stock Ageing", label: "Stock Ageing", filter: "item_code" },
    { report: "Batch Expiry", label: "Batch Expiry", filter: "item_code" },
  ],
  Warehouse: [
    { report: "Stock Balance", label: "Stock Balance", filter: "warehouse" },
    { report: "Stock Ledger", label: "Stock Ledger", filter: "warehouse" },
    { report: "Stock Ageing", label: "Stock Ageing", filter: "warehouse" },
  ],
  "Fixed Asset": [{ report: "Fixed Asset Maintenance Cost", label: "Repairs & Maintenance Cost", filter: "asset" }],
  Customer: [{ report: "Customer Ledger", label: "Customer Ledger", filter: "customer" }],
  Supplier: [{ report: "Supplier Ledger", label: "Supplier Ledger", filter: "supplier" }],
};

export const reportLinkHash = (l: ReportLink, name: string) => `#/report/${encodeURIComponent(l.report)}?${l.filter}=${encodeURIComponent(name)}`;
