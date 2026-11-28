import { askConfirm, askPrompt, askAlert } from "../ui/ask";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, errorMessage, type FinancialLayoutColumn, type FinancialLayoutDefinition, type FinancialLayoutInfo, type FinancialLayoutRow } from "../api";
import Icon from "../ui/Icon";

const rowTypes = [
  ["account", "Account"], ["account_range", "Account range"], ["account_category", "Account category"],
  ["dimension", "Dimension"], ["formula", "Formula"], ["text", "Text"], ["blank", "Blank"],
];
const columnTypes = [
  ["net_change", "Net change"], ["balance_at_date", "Balance at date"], ["period_to_date", "Period to date"],
  ["year_to_date", "Year to date"], ["same_period_last_year", "Same period last year"], ["opening_balance", "Opening balance"], ["budget", "Budget (requires budget module)"],
  ["formula", "Formula"], ["text", "Text"], ["blank", "Blank"],
];
const periods = [["day", "Day"], ["week", "Week"], ["month", "Month"], ["quarter", "Quarter"], ["year", "Year"], ["accounting_period", "Accounting period"]];
const blankRow = (n: number): FinancialLayoutRow => ({ code: `ROW_${n}`, description: "New report row", type: "account", indent: 0, bold: false, italic: false, show: true, account_no: "" });
const blankColumn = (n: number): FinancialLayoutColumn => ({ code: `COL_${n}`, caption: `Column ${n}`, type: "net_change", date_mode: "current_period", period: "month", offset: 0, width: 16 });
const blankDefinition = (): FinancialLayoutDefinition => ({ rows: [blankRow(1)], columns: [blankColumn(1)], options: {} });

const templates: { name: string; description: string; definition: FinancialLayoutDefinition }[] = [
  { name: "Profit & Loss", description: "Revenue, cost of sales, gross profit, expenses and net profit.", definition: {
    rows: [
      { ...blankRow(1), code: "REVENUE", description: "Revenue", type: "account_range", from_account: "4000", to_account: "4999", bold: true },
      { ...blankRow(2), code: "COST_OF_SALES", description: "Cost of sales", type: "account_range", from_account: "5000", to_account: "5999", sign: -1 },
      { ...blankRow(3), code: "GROSS_PROFIT", description: "Gross profit", type: "formula", formula: "[REVENUE]+[COST_OF_SALES]", bold: true },
      { ...blankRow(4), code: "OPERATING_EXPENSES", description: "Operating expenses", type: "account_range", from_account: "6000", to_account: "6999", sign: -1 },
      { ...blankRow(5), code: "NET_PROFIT", description: "Net profit", type: "formula", formula: "[GROSS_PROFIT]+[OPERATING_EXPENSES]", bold: true },
    ],
    columns: [
      { ...blankColumn(1), code: "CURRENT", caption: "Current period", type: "net_change", period: "month" },
      { ...blankColumn(2), code: "PRIOR", caption: "Prior year comparable", type: "same_period_last_year", period: "month", offset: -12 },
      { ...blankColumn(3), code: "VARIANCE", caption: "Variance vs prior year", type: "formula", formula: "[CURRENT]-[PRIOR]" },
      { ...blankColumn(4), code: "VARIANCE_PCT", caption: "Variance (%)", type: "formula", formula: "(([CURRENT]-[PRIOR])/[PRIOR])*100" },
    ], options: { statement: "profit_and_loss" },
  }},
  { name: "Balance Sheet", description: "Assets, liabilities, equity and total liabilities and equity.", definition: {
    rows: [
      { ...blankRow(1), code: "ASSETS", description: "ASSETS", type: "text", bold: true },
      { ...blankRow(2), code: "CURRENT_ASSETS", description: "Current assets", type: "account_range", from_account: "1000", to_account: "1499" },
      { ...blankRow(3), code: "NONCURRENT_ASSETS", description: "Non-current assets", type: "account_range", from_account: "1500", to_account: "1999" },
      { ...blankRow(4), code: "TOTAL_ASSETS", description: "Total assets", type: "formula", formula: "[CURRENT_ASSETS]+[NONCURRENT_ASSETS]", bold: true },
      { ...blankRow(5), code: "LIABILITIES_EQUITY", description: "LIABILITIES AND EQUITY", type: "text", bold: true },
      { ...blankRow(6), code: "LIABILITIES", description: "Liabilities", type: "account_range", from_account: "2000", to_account: "2999" },
      { ...blankRow(7), code: "EQUITY", description: "Equity", type: "account_range", from_account: "3000", to_account: "3999" },
      { ...blankRow(8), code: "TOTAL_LIABILITIES_EQUITY", description: "Total liabilities and equity", type: "formula", formula: "[LIABILITIES]+[EQUITY]", bold: true },
    ],
    columns: [{ ...blankColumn(1), code: "AS_AT", caption: "As at date", type: "balance_at_date", date_mode: "as_of", period: "year" }],
    options: { statement: "balance_sheet" },
  }},
  { name: "Comparative Income Statement", description: "Current period, prior-year comparison, variance and year-to-date performance.", definition: {
    rows: [
      { ...blankRow(1), code: "INCOME", description: "Revenue and other income", type: "account_category", category: "Income", bold: true },
      { ...blankRow(2), code: "EXPENSES", description: "Expenses", type: "account_category", category: "Expense", bold: true },
      { ...blankRow(3), code: "NET_PROFIT", description: "Profit / (Loss) for the period", type: "formula", formula: "[INCOME]-[EXPENSES]", bold: true },
      { ...blankRow(4), code: "NET_MARGIN", description: "Net profit margin (%)", type: "formula", formula: "([NET_PROFIT]/[INCOME])*100", indent: 1 },
    ],
    columns: [
      { ...blankColumn(1), code: "CURRENT", caption: "Current period", type: "net_change" },
      { ...blankColumn(2), code: "PRIOR", caption: "Prior year comparable", type: "same_period_last_year", offset: -12 },
      { ...blankColumn(3), code: "VARIANCE", caption: "Variance", type: "formula", formula: "[CURRENT]-[PRIOR]" },
      { ...blankColumn(4), code: "VARIANCE_PCT", caption: "Variance (%)", type: "formula", formula: "(([CURRENT]-[PRIOR])/[PRIOR])*100" },
      { ...blankColumn(5), code: "YTD", caption: "Current YTD", type: "year_to_date", period: "year" },
      { ...blankColumn(6), code: "PRIOR_YTD", caption: "Prior YTD", type: "year_to_date", period: "year", offset: -1 },
    ], options: { statement: "comparative_income_statement", currency_basis: "company_base_currency" },
  }},
  { name: "Comparative Statement of Financial Position", description: "Assets, liabilities and equity with a prior-year comparable and balance check.", definition: {
    rows: [
      { ...blankRow(1), code: "ASSETS", description: "Total assets", type: "account_category", category: "Asset", bold: true },
      { ...blankRow(2), code: "LIABILITIES", description: "Total liabilities", type: "account_category", category: "Liability", bold: true },
      { ...blankRow(3), code: "EQUITY", description: "Total equity", type: "account_category", category: "Equity", bold: true },
      { ...blankRow(4), code: "TOTAL_LIABILITIES_EQUITY", description: "Total liabilities and equity", type: "formula", formula: "[LIABILITIES]+[EQUITY]", bold: true },
      { ...blankRow(5), code: "BALANCE_CHECK", description: "Assets less liabilities and equity (must be zero)", type: "formula", formula: "[ASSETS]-[TOTAL_LIABILITIES_EQUITY]", bold: true },
    ],
    columns: [
      { ...blankColumn(1), code: "CURRENT", caption: "Current as at", type: "balance_at_date", date_mode: "as_of", period: "year" },
      { ...blankColumn(2), code: "PRIOR", caption: "Prior-year comparable", type: "balance_at_date", date_mode: "as_of", period: "year", offset: -1 },
      { ...blankColumn(3), code: "MOVEMENT", caption: "Movement", type: "formula", formula: "[CURRENT]-[PRIOR]" },
    ], options: { statement: "comparative_statement_of_financial_position", currency_basis: "company_base_currency" },
  }},
  { name: "Statement of Changes in Equity - Mapping Template", description: "Opening balance, movements and closing balance reconciliation. Map detailed equity components before publication.", definition: {
    rows: [
      { ...blankRow(1), code: "EQUITY", description: "Total equity", type: "account_category", category: "Equity", bold: true },
    ],
    columns: [
      { ...blankColumn(1), code: "OPENING", caption: "Opening balance", type: "opening_balance", period: "day" },
      { ...blankColumn(2), code: "MOVEMENTS", caption: "Movements during period", type: "net_change" },
      { ...blankColumn(3), code: "CLOSING", caption: "Closing balance", type: "balance_at_date" },
      { ...blankColumn(4), code: "RECONCILIATION", caption: "Reconciliation (must be zero)", type: "formula", formula: "[OPENING]+[MOVEMENTS]-[CLOSING]" },
    ], options: { statement: "equity_movement_reconciliation", currency_basis: "company_base_currency", requires_equity_account_mapping_review: true },
  }},
];

function move<T>(items: T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length || from === to) return items;
  const next = [...items]; const [item] = next.splice(from, 1); next.splice(to, 0, item); return next;
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="frd-field"><span>{label}</span>{children}</label>;
}

export default function FinancialReportDesigner() {
  const [layouts, setLayouts] = useState<FinancialLayoutInfo[]>([]);
  const [current, setCurrent] = useState<FinancialLayoutInfo | null>(null);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const [definition, setDefinition] = useState<FinancialLayoutDefinition>(blankDefinition());
  const [selectedRow, setSelectedRow] = useState(0);
  const [selectedColumn, setSelectedColumn] = useState(0);
  const [tab, setTab] = useState<"rows" | "columns" | "preview">("rows");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dragRow, setDragRow] = useState<number | null>(null);
  const [dragColumn, setDragColumn] = useState<number | null>(null);

  const refresh = async () => { setLayouts(await api.financialLayouts()); };
  useEffect(() => { refresh().catch((e) => setError(errorMessage(e))); }, []);
  const row = definition.rows[selectedRow];
  const column = definition.columns[selectedColumn];
  const updateRow = (patch: Partial<FinancialLayoutRow>) => setDefinition((d) => ({ ...d, rows: d.rows.map((r, i) => i === selectedRow ? { ...r, ...patch } : r) }));
  const updateColumn = (patch: Partial<FinancialLayoutColumn>) => setDefinition((d) => ({ ...d, columns: d.columns.map((c, i) => i === selectedColumn ? { ...c, ...patch } : c) }));

  function newLayout() {
    setCurrent(null); setName(""); setShared(false); setDefinition(blankDefinition());
    setSelectedRow(0); setSelectedColumn(0); setTab("rows"); setError(""); setNotice("");
  }
  function loadTemplate(index: number) {
    const t = templates[index];
    setCurrent(null); setName(t.name); setShared(false);
    setDefinition(JSON.parse(JSON.stringify(t.definition)) as FinancialLayoutDefinition);
    setSelectedRow(0); setSelectedColumn(0); setTab("rows"); setError(""); setNotice(`${t.name} template loaded. Review the account ranges against your chart of accounts before saving.`);
  }
  async function openLayout(id: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      const item = await api.financialLayout(id);
      setCurrent(item); setName(item.name); setShared(item.shared); setDefinition(item.definition);
      setSelectedRow(0); setSelectedColumn(0); setTab("rows");
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setError(""); setNotice("");
    try {
      const valid = await api.validateFinancialLayout(definition);
      const saved = await api.saveFinancialLayout({ name, definition: valid, shared }, current?.can_edit ? current.id : undefined);
      setCurrent(saved); setName(saved.name); setDefinition(saved.definition);
      await refresh(); setNotice("Financial report layout saved.");
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!current || !await askConfirm(`Delete financial report layout “${current.name}”?`)) return;
    setBusy(true); setError("");
    try { await api.deleteFinancialLayout(current.id); await refresh(); newLayout(); setNotice("Layout deleted."); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  function addRow() {
    const next = [...definition.rows, blankRow(definition.rows.length + 1)];
    setDefinition({ ...definition, rows: next }); setSelectedRow(next.length - 1); setTab("rows");
  }
  function addColumn() {
    const next = [...definition.columns, blankColumn(definition.columns.length + 1)];
    setDefinition({ ...definition, columns: next }); setSelectedColumn(next.length - 1); setTab("columns");
  }
  function deleteRow(index: number) {
    if (definition.rows.length === 1) return;
    const next = definition.rows.filter((_, i) => i !== index);
    setDefinition({ ...definition, rows: next }); setSelectedRow(Math.min(selectedRow, next.length - 1));
  }
  function deleteColumn(index: number) {
    if (definition.columns.length === 1) return;
    const next = definition.columns.filter((_, i) => i !== index);
    setDefinition({ ...definition, columns: next }); setSelectedColumn(Math.min(selectedColumn, next.length - 1));
  }
  const insertReference = (code: string, setter: (value: string) => void, existing: string) => setter(`${existing}${existing && !/[+\-*/(]$/.test(existing) ? "+" : ""}[${code}]`);

  return <div className="frd-page">
    <div className="frd-header">
      <div><div className="eyebrow">FINANCIAL REPORTING</div><h1>Financial Report Designer</h1><p>Define statement rows, comparative columns and calculation formulas.</p></div>
      <div className="frd-actions"><button className="rbtn" type="button" onClick={newLayout}><Icon name="plus" /> New layout</button><button className="rbtn primary" type="button" disabled={busy || !name.trim()} onClick={save}><Icon name="save" /> {current && !current.can_edit ? "Save as copy" : "Save layout"}</button></div>
    </div>
    {error && <div className="error" role="alert">{error}</div>}
    {notice && <div className="success" role="status">{notice}</div>}
    <div className="frd-workspace">
      <aside className="frd-library">
        <div className="frd-panel-head"><strong>Saved layouts</strong><span>{layouts.length}</span></div>
        {layouts.length === 0 && <p className="muted frd-empty">Your saved financial reports will appear here.</p>}
        {layouts.map((item) => <div key={item.id} className={`frd-layout-item${current?.id === item.id ? " selected" : ""}`}><button type="button" className="frd-layout-open" onClick={() => openLayout(item.id)}><strong>{item.name}</strong><small>{item.shared ? "Shared with company" : "Private"}{item.can_edit ? " · Editable" : " · Read only"}</small></button><button type="button" className="rbtn primary frd-run-small" onClick={() => { window.location.hash = `#/financial-report-run?id=${encodeURIComponent(item.id)}`; }}>Run</button></div>)}
        <div className="frd-divider" />
        <strong className="frd-template-title">Start from a template</strong>
        {templates.map((t, i) => <button className="frd-template" key={t.name} type="button" onClick={() => loadTemplate(i)}><b>{t.name}</b><small>{t.description}</small></button>)}
      </aside>
      <section className="frd-editor">
        <div className="frd-namebar">
          <Field label="Report name"><input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} placeholder="e.g. Monthly management accounts" /></Field>
          <label className="frd-share"><input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} /> Share with company</label>
          {current && current.can_edit && <button type="button" className="rbtn danger" onClick={remove} disabled={busy}><Icon name="trash" /> Delete</button>}
        </div>
        <div className="frd-tabs">
          <button className={tab === "rows" ? "active" : ""} onClick={() => setTab("rows")} type="button">Row definitions <span>{definition.rows.length}</span></button>
          <button className={tab === "columns" ? "active" : ""} onClick={() => setTab("columns")} type="button">Column definitions <span>{definition.columns.length}</span></button>
          <button className={tab === "preview" ? "active" : ""} onClick={() => setTab("preview")} type="button">Layout preview</button>
        </div>
        {tab === "rows" && <div className="frd-builder">
          <div className="frd-list">
            <div className="frd-list-title"><strong>Rows</strong><button type="button" className="rbtn" onClick={addRow}>＋ Add row</button></div>
            {definition.rows.map((r, i) => <div key={`${r.code}-${i}`} draggable onDragStart={() => setDragRow(i)} onDragOver={(e) => e.preventDefault()} onDrop={() => { if (dragRow !== null) { const rows = move(definition.rows, dragRow, i); setDefinition({ ...definition, rows }); setSelectedRow(i); setDragRow(null); } }} className={`frd-row-choice${selectedRow === i ? " selected" : ""}`} onClick={() => setSelectedRow(i)}>
              <span className="frd-grip" title="Drag to reorder">⠿</span><span className="frd-row-index">{i + 1}</span><span className="frd-row-label"><b>{r.description || r.code}</b><small>{r.code} · {rowTypes.find((x) => x[0] === r.type)?.[1] ?? r.type}</small></span>
              <button type="button" className="frd-icon-btn" title="Move up" onClick={(e) => { e.stopPropagation(); const rows = move(definition.rows, i, i - 1); setDefinition({ ...definition, rows }); setSelectedRow(i - 1 < 0 ? i : i - 1); }}>↑</button>
              <button type="button" className="frd-icon-btn" title="Move down" onClick={(e) => { e.stopPropagation(); const rows = move(definition.rows, i, i + 1); setDefinition({ ...definition, rows }); setSelectedRow(Math.min(i + 1, rows.length - 1)); }}>↓</button>
            </div>)}
          </div>
          {row && <div className="frd-properties">
            <div className="frd-list-title"><strong>Row properties</strong><button type="button" className="rbtn danger" disabled={definition.rows.length === 1} onClick={() => deleteRow(selectedRow)}>Remove row</button></div>
            <div className="frd-form-grid">
              <Field label="Row code"><input value={row.code} onChange={(e) => updateRow({ code: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_") })} /></Field>
              <Field label="Row type"><select value={row.type} onChange={(e) => updateRow({ type: e.target.value, formula: "", account_no: "", from_account: "", to_account: "", category: "", dimension: "" })}>{rowTypes.map(([v, l]) => <option value={v} key={v}>{l}</option>)}</select></Field>
              <Field label="Description"><input value={row.description} onChange={(e) => updateRow({ description: e.target.value })} /></Field>
              {row.type === "account" && <Field label="Account number"><input value={row.account_no ?? ""} onChange={(e) => updateRow({ account_no: e.target.value })} /></Field>}
              {row.type === "account_range" && <><Field label="From account"><input value={row.from_account ?? ""} onChange={(e) => updateRow({ from_account: e.target.value })} /></Field><Field label="To account"><input value={row.to_account ?? ""} onChange={(e) => updateRow({ to_account: e.target.value })} /></Field></>}
              {row.type === "account_category" && <Field label="Account category"><input value={row.category ?? ""} onChange={(e) => updateRow({ category: e.target.value })} /></Field>}
              {row.type === "dimension" && <><Field label="Dimension"><input value={row.dimension ?? ""} onChange={(e) => updateRow({ dimension: e.target.value })} /></Field><Field label="Dimension value"><input value={row.dimension_value ?? ""} onChange={(e) => updateRow({ dimension_value: e.target.value })} /></Field></>}
              {row.type === "formula" && <Field label="Formula"><input value={row.formula ?? ""} onChange={(e) => updateRow({ formula: e.target.value })} placeholder="[REVENUE]-[COST]" /></Field>}
              {row.type === "text" && <Field label="Display text"><input value={row.text ?? ""} onChange={(e) => updateRow({ text: e.target.value })} /></Field>}
              {["account", "account_range", "account_category", "dimension"].includes(row.type) && <Field label="Sign"><select value={row.sign ?? 1} onChange={(e) => updateRow({ sign: Number(e.target.value) })}><option value={1}>Normal (+1)</option><option value={-1}>Reverse (-1)</option></select></Field>}
              <Field label="Indent level"><input type="number" min="0" max="10" value={row.indent} onChange={(e) => updateRow({ indent: Number(e.target.value) })} /></Field>
            </div>
            {row.type === "formula" && <div className="frd-reference-box"><b>Insert row reference</b><div>{definition.rows.slice(0, selectedRow).map((r) => <button type="button" key={r.code} className="frd-ref-chip" onClick={() => updateRow({ formula: `${row.formula ?? ""}${row.formula ? "+" : ""}[${r.code}]` })}>[{r.code}]</button>)}</div><small>Only rows above this formula row can be referenced.</small></div>}
            <div className="frd-checks"><label><input type="checkbox" checked={row.bold} onChange={(e) => updateRow({ bold: e.target.checked })} /> Bold</label><label><input type="checkbox" checked={row.italic} onChange={(e) => updateRow({ italic: e.target.checked })} /> Italic</label><label><input type="checkbox" checked={row.show} onChange={(e) => updateRow({ show: e.target.checked })} /> Show row</label></div>
          </div>}
        </div>}
        {tab === "columns" && <div className="frd-builder">
          <div className="frd-list">
            <div className="frd-list-title"><strong>Columns</strong><button type="button" className="rbtn" onClick={addColumn}>＋ Add column</button></div>
            {definition.columns.map((c, i) => <div key={`${c.code}-${i}`} draggable onDragStart={() => setDragColumn(i)} onDragOver={(e) => e.preventDefault()} onDrop={() => { if (dragColumn !== null) { const columns = move(definition.columns, dragColumn, i); setDefinition({ ...definition, columns }); setSelectedColumn(i); setDragColumn(null); } }} className={`frd-row-choice${selectedColumn === i ? " selected" : ""}`} onClick={() => setSelectedColumn(i)}>
              <span className="frd-grip">⠿</span><span className="frd-row-index">{i + 1}</span><span className="frd-row-label"><b>{c.caption}</b><small>{c.code} · {columnTypes.find((x) => x[0] === c.type)?.[1] ?? c.type}</small></span>
              <button type="button" className="frd-icon-btn" title="Move left" onClick={(e) => { e.stopPropagation(); const columns = move(definition.columns, i, i - 1); setDefinition({ ...definition, columns }); setSelectedColumn(Math.max(0, i - 1)); }}>←</button>
              <button type="button" className="frd-icon-btn" title="Move right" onClick={(e) => { e.stopPropagation(); const columns = move(definition.columns, i, i + 1); setDefinition({ ...definition, columns }); setSelectedColumn(Math.min(i + 1, columns.length - 1)); }}>→</button>
            </div>)}
          </div>
          {column && <div className="frd-properties">
            <div className="frd-list-title"><strong>Column properties</strong><button type="button" className="rbtn danger" disabled={definition.columns.length === 1} onClick={() => deleteColumn(selectedColumn)}>Remove column</button></div>
            <div className="frd-form-grid">
              <Field label="Column code"><input value={column.code} onChange={(e) => updateColumn({ code: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_") })} /></Field>
              <Field label="Column type"><select value={column.type} onChange={(e) => updateColumn({ type: e.target.value, formula: "" })}>{columnTypes.map(([v, l]) => <option value={v} key={v}>{l}</option>)}</select></Field>
              <Field label="Caption"><input value={column.caption} onChange={(e) => updateColumn({ caption: e.target.value })} /></Field>
              {column.type !== "formula" && column.type !== "text" && column.type !== "blank" && <>
                <Field label="Date mode"><select value={column.date_mode} onChange={(e) => updateColumn({ date_mode: e.target.value })}><option value="current_period">Current period</option><option value="custom">Custom date range</option><option value="as_of">As of date</option></select></Field>
                <Field label="Period"><select value={column.period} onChange={(e) => updateColumn({ period: e.target.value })}>{periods.map(([v, l]) => <option value={v} key={v}>{l}</option>)}</select></Field>
                <Field label="Period offset"><input type="number" min="-120" max="120" value={column.offset} onChange={(e) => updateColumn({ offset: Number(e.target.value) })} /><small>Negative values refer to earlier periods; for example -12 means twelve months earlier.</small></Field>
              </>}
              {column.type === "formula" && <Field label="Formula"><input value={column.formula ?? ""} onChange={(e) => updateColumn({ formula: e.target.value })} placeholder="[CURRENT]-[PRIOR]" /></Field>}
              {column.type === "text" && <Field label="Display text"><input value={column.text ?? ""} onChange={(e) => updateColumn({ text: e.target.value })} /></Field>}
              <Field label="Display width"><input type="number" min="6" max="60" value={column.width} onChange={(e) => updateColumn({ width: Number(e.target.value) })} /></Field>
            </div>
            {column.type === "formula" && <div className="frd-reference-box"><b>Insert column reference</b><div>{definition.columns.slice(0, selectedColumn).map((c) => <button type="button" key={c.code} className="frd-ref-chip" onClick={() => updateColumn({ formula: `${column.formula ?? ""}${column.formula ? "+" : ""}[${c.code}]` })}>[{c.code}]</button>)}</div><small>Only columns to the left of this formula column can be referenced.</small></div>}
          </div>}
        </div>}
        {tab === "preview" && <div className="frd-preview-wrap">
          <div className="frd-preview-note">Structure preview only. Amounts appear when a ledger adapter supplies balances and period values.</div>
          <div className="frd-preview-title">{name || "Untitled financial report"}</div>
          <table className="frd-preview-table"><thead><tr><th>Row description</th>{definition.columns.map((c) => <th key={c.code}>{c.caption}</th>)}</tr></thead>
            <tbody>{definition.rows.filter((r) => r.show).map((r) => <tr key={r.code} className={r.bold ? "strong" : ""}><td style={{ paddingLeft: `${12 + r.indent * 18}px`, fontStyle: r.italic ? "italic" : "normal" }}>{r.description}</td>{definition.columns.map((c) => <td key={c.code}>{r.type === "text" ? "" : r.type === "blank" ? "" : "—"}</td>)}</tr>)}</tbody></table>
        </div>}
        <div className="frd-footer"><span className="muted">{definition.rows.length} rows · {definition.columns.length} columns</span><button type="button" className="rbtn primary" disabled={busy || !name.trim()} onClick={save}>Validate & save</button></div>
      </section>
    </div>
  </div>;
}
