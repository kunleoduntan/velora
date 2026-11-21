import { useState } from "react";
import LinkField from "./LinkField";

interface Props {
  kind: "Receipt" | "Payment";
  invoiceTotal: number;
  title?: string;
  onCancel: () => void;
  onConfirm: (bankAccount: string, amount: number) => void;
}

/** Collects the bank/cash account and amount for a Receipt or Payment created from an invoice. */
export default function SettlementDialog({ kind, invoiceTotal, title, onCancel, onConfirm }: Props) {
  const [account, setAccount] = useState("");
  const [amount, setAmount] = useState(String(invoiceTotal));
  const [error, setError] = useState("");

  function confirm() {
    const value = Number(amount);
    if (!account.trim()) return setError("Select the Bank Account.");
    if (!Number.isFinite(value) || value <= 0) return setError("Enter an amount greater than zero.");
    if (value > invoiceTotal) return setError(`The amount cannot exceed the outstanding balance of ${invoiceTotal}.`);
    onConfirm(account.trim(), value);
  }

  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title || `Create ${kind}`}>
        <header><h2>{title || `Create ${kind}`}</h2></header>
        <div className="dialog-body">
          <label className="field"><span>Bank Account</span>
            <LinkField doctype="Bank Account" value={account} onChange={setAccount} ariaLabel="Bank Account" /></label>
          <label className="field"><span>Amount (maximum {invoiceTotal})</span>
            <input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} aria-label="Settlement amount" /></label>
          {error && <p className="form-error" role="alert">{error}</p>}
        </div>
        <footer>
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn primary" onClick={confirm}>{title || `Create ${kind}`}</button>
        </footer>
      </div>
    </div>
  );
}
