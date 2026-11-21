import { useState } from "react";
import LinkField from "./LinkField";

export interface FlowOption { key: string; label: string; doctype: string }

/** Extra choices some Create From actions need (which account to post to, which warehouse issues or receives the stock). */
export default function FlowOptionsDialog({ title, options, onCancel, onConfirm }: {
  title: string; options: FlowOption[]; onCancel: () => void; onConfirm: (values: Record<string, string>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <header><h2>{title}</h2></header>
        <div className="dialog-body">
          {options.map((o) => (
            <label className="field" key={o.key}><span>{o.label}</span>
              <LinkField doctype={o.doctype} value={values[o.key] ?? ""} onChange={(v) => setValues({ ...values, [o.key]: v })} ariaLabel={o.label} /></label>
          ))}
          <p className="muted">Leave a choice empty to use the item's own account or the document's warehouse where one is set.</p>
        </div>
        <footer>
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn primary" onClick={() => onConfirm(Object.fromEntries(Object.entries(values).filter(([, v]) => v)))}>{title}</button>
        </footer>
      </div>
    </div>
  );
}

export const FLOW_OPTIONS: Record<string, FlowOption[]> = {
  "Material Request:Purchase Order": [{ key: "party", label: "Supplier to order from", doctype: "Supplier" }],
  "Request for Quotation:Supplier Quotation": [{ key: "supplier", label: "Supplier who quoted", doctype: "Supplier" }],
  "Material Request:Request for Quotation": [{ key: "supplier", label: "Supplier to ask (more can be added afterwards)", doctype: "Supplier" }],
  "Sales Quotation:Sales Invoice": [{ key: "revenue_account", label: "Revenue Account", doctype: "Account" }, { key: "warehouse", label: "Dispatch Warehouse (stock items)", doctype: "Warehouse" }],
  "Purchase Order:Purchase Invoice": [{ key: "expense_account", label: "Expense Account", doctype: "Account" }, { key: "warehouse", label: "Receiving Warehouse (stock items)", doctype: "Warehouse" }],
};
