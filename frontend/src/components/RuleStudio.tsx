import { askConfirm, askPrompt, askAlert } from "../ui/ask";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type RuleRow = {
  name: string; title: string; description?: string; scope: string; doctype?: string;
  definition: Record<string, unknown>; enabled: boolean; version: number;
};

const starter = JSON.stringify({
  all: [
    { condition: { field: "grand_total", operator: ">", value: 5000000 } },
    { condition: { field: "docstatus", operator: "=", value: 0 } },
  ],
}, null, 2);

export default function RuleStudio() {
  const [rows, setRows] = useState<RuleRow[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [scope, setScope] = useState("global");
  const [doctype, setDoctype] = useState("");
  const [definition, setDefinition] = useState(starter);
  const [sample, setSample] = useState('{"grand_total": 6500000, "docstatus": 0}');
  const [result, setResult] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    const data = await api.rules();
    setRows(data as RuleRow[]);
  };
  useEffect(() => { refresh().catch((e) => setError(errorMessage(e))); }, []);

  const load = async (ruleName: string) => {
    setError(""); setResult("");
    try {
      const row = await api.rule(ruleName) as RuleRow;
      setSelected(row.name); setName(row.name); setTitle(row.title); setDescription(row.description || "");
      setScope(row.scope); setDoctype(row.doctype || "");
      setDefinition(JSON.stringify(row.definition, null, 2));
    } catch (e) { setError(errorMessage(e)); }
  };

  const clear = () => {
    setSelected(""); setName(""); setTitle(""); setDescription(""); setScope("global");
    setDoctype(""); setDefinition(starter); setResult(""); setError("");
  };

  const save = async () => {
    setBusy(true); setError(""); setResult("");
    try {
      const parsed = JSON.parse(definition) as Record<string, unknown>;
      const payload = { name, title, description, scope, doctype: scope === "doctype" ? doctype : undefined,
        definition: parsed, enabled: true };
      const saved = selected ? await api.updateRule(selected, payload) : await api.saveRule(payload);
      setSelected(saved.name); await refresh(); setResult(`Saved version ${saved.version}.`);
    } catch (e) { setError(e instanceof SyntaxError ? "Rule definition is not valid JSON." : errorMessage(e)); }
    finally { setBusy(false); }
  };

  const test = async () => {
    if (!selected) { setError("Save the rule before testing it."); return; }
    setBusy(true); setError(""); setResult("");
    try {
      const doc = JSON.parse(sample) as Record<string, unknown>;
      const response = await api.testRule(selected, doc);
      setResult(response.matched ? "MATCHED — the rule conditions are satisfied." : "NOT MATCHED — the rule conditions are not satisfied.");
    } catch (e) { setError(e instanceof SyntaxError ? "Sample document is not valid JSON." : errorMessage(e)); }
    finally { setBusy(false); }
  };

  const remove = async () => {
    if (!selected || !await askConfirm(`Delete rule ${selected}?`)) return;
    setBusy(true);
    try { await api.deleteRule(selected); clear(); await refresh(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  };

  return <div className="page rule-studio">
    <div className="page-header">
      <div><h1>Rule Studio</h1><p className="muted">Build reusable business policies using safe, declarative conditions. Rules are data, not executable scripts.</p></div>
      <div className="actions"><button className="rbtn" onClick={clear}>＋ New rule</button><button className="rbtn primary" disabled={busy || !name.trim() || !title.trim()} onClick={save}>{busy ? "Working…" : "Save rule"}</button></div>
    </div>
    {error && <div className="notice danger" role="alert">{error}</div>}
    {result && <div className="notice success" role="status">{result}</div>}
    <div className="rule-studio-grid">
      <section className="panel">
        <div className="panel-heading"><h2>Saved rules</h2><button className="rbtn" onClick={() => refresh().catch((e) => setError(errorMessage(e)))}>Refresh</button></div>
        {rows.length === 0 && <p className="muted">No rules have been created in this company.</p>}
        <div className="rule-list">{rows.map((r) => <button key={r.name} className={`rule-list-item ${selected === r.name ? "selected" : ""}`} onClick={() => load(r.name)}>
          <span><strong>{r.title}</strong><small>{r.name} · {r.scope} · v{r.version}</small></span><span className={`badge ${r.enabled ? "success" : ""}`}>{r.enabled ? "Enabled" : "Disabled"}</span>
        </button>)}</div>
      </section>
      <section className="panel rule-editor">
        <h2>{selected ? `Edit ${selected}` : "New rule definition"}</h2>
        <div className="form-grid">
          <label>Rule ID<input value={name} disabled={!!selected} onChange={(e) => setName(e.target.value)} placeholder="HighValuePurchase" /></label>
          <label>Display title<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="High Value Purchase" /></label>
          <label>Scope<select value={scope} onChange={(e) => setScope(e.target.value)}><option value="global">Global</option><option value="doctype">DocType</option></select></label>
          {scope === "doctype" && <label>DocType<input value={doctype} onChange={(e) => setDoctype(e.target.value)} placeholder="Purchase Order" /></label>}
          <label className="wide">Description<input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What business decision does this rule represent?" /></label>
        </div>
        <label className="rule-code-label">Rule expression (JSON)<textarea spellCheck={false} value={definition} onChange={(e) => setDefinition(e.target.value)} rows={15} /></label>
        <div className="rule-help"><strong>Supported structure</strong><code>{"{ \"all\": [ { \"condition\": { \"field\": \"amount\", \"operator\": \">\", \"value\": 100 } } ] }"}</code><span>Groups: all, any, not. Operators: =, !=, &gt;, &gt;=, &lt;, &lt;=, in, not in, contains, not contains, starts_with, ends_with, is_set, is_not_set. Context fields begin with $ (for example $user).</span></div>
        <div className="rule-test">
          <h3>Test this rule</h3><label>Sample document (JSON)<textarea spellCheck={false} rows={5} value={sample} onChange={(e) => setSample(e.target.value)} /></label>
          <div className="actions"><button className="rbtn" disabled={busy || !selected} onClick={test}>Test saved rule</button>{selected && <button className="rbtn danger" disabled={busy} onClick={remove}>Delete rule</button>}</div>
        </div>
      </section>
    </div>
  </div>;
}
