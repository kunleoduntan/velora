import { useEffect, useState } from "react";
import { api, errorMessage, type DisplayFormatState } from "../api";
import { setDisplayFormat } from "../format";

/** Pick how this company shows dates and numbers. The choice applies to everyone in the company. */
export default function DisplayFormatSettings() {
  const [state, setState] = useState<DisplayFormatState | null>(null);
  const [date, setDate] = useState("");
  const [number, setNumber] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => { api.displayFormat().then(s => { setState(s); setDate(s.date); setNumber(s.number); }).catch(e => setError(errorMessage(e))); }, []);
  async function save() {
    setError(""); setMessage("");
    try {
      const s = await api.saveDisplayFormat(date, number);
      setState(s); setDisplayFormat(s); setMessage("Saved. Open lists and reports again to see it.");
    } catch (e) { setError(errorMessage(e)); }
  }
  if (!state) return <div className="panel">{error ? <div className="error" role="alert">{error}</div> : <p className="muted">Loading…</p>}</div>;
  const example = (list: { value: string; example: string }[], v: string) => list.find(x => x.value === v)?.example ?? "";
  return (
    <div className="panel">
      <div className="page-head"><div className="titles"><h1>Date &amp; Number Format</h1><span className="muted">How dates and amounts are shown to everyone in this company</span></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      {message && <div className="success" role="status">{message}</div>}
      <label>Date format
        <select value={date} onChange={e => setDate(e.target.value)}>{state.dates.map(d => <option key={d.value} value={d.value}>{d.value} (for example {d.example})</option>)}</select>
      </label>
      <label>Number format
        <select value={number} onChange={e => setNumber(e.target.value)}>{state.numbers.map(n => <option key={n.value} value={n.value}>{n.example}</option>)}</select>
      </label>
      <p className="muted" aria-label="Preview">Preview: {example(state.dates, date)} · {example(state.numbers, number)}</p>
      <div className="fe-tools"><button className="rbtn primary" disabled={date === state.date && number === state.number} onClick={() => void save()}>Save</button></div>
    </div>
  );
}
