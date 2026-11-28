import { useEffect, useState } from "react";
import { api, downloadBlob, errorMessage, governance } from "../api";
import { Card, Kpi, Tone } from "./centre";

type Obj = Record<string, unknown>;
const num = (v: unknown) => Number(v ?? 0);

/** Entity and period pickers shared by the IFRS and SASB screens. */
function useEntityPeriod() {
  const [entities, setEntities] = useState<string[]>([]), [entity, setEntity] = useState(""), [periods, setPeriods] = useState<string[]>([]), [period, setPeriod] = useState(""), [error, setError] = useState("");
  useEffect(() => { api.list("Governance Entity", { fields: ["name"], limit: 200 }).then(r => { const n = r.map(x => String(x.name)); setEntities(n); setEntity(n[0] ?? ""); }).catch(e => setError(errorMessage(e))); }, []);
  useEffect(() => {
    if (!entity) { setPeriods([]); setPeriod(""); return; }
    api.list("Sustainability Reporting Period", { fields: ["period_name"], filters: [["governance_entity", "=", entity]], limit: 100 }).then(r => { const n = r.map(x => String(x.period_name)); setPeriods(n); setPeriod(n[0] ?? ""); }).catch(e => setError(errorMessage(e)));
  }, [entity]);
  const picker = (
    <div className="gov-actions">
      <label>Entity <select value={entity} onChange={e => setEntity(e.target.value)}>{entities.map(n => <option key={n}>{n}</option>)}</select></label>
      <label>Period <select value={period} onChange={e => setPeriod(e.target.value)}>{periods.map(n => <option key={n}>{n}</option>)}</select></label>
    </div>);
  return { entity, period, picker, error, setError };
}

function download(b64: string, filename: string, type: string) {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  downloadBlob(new Blob([bytes], { type }), filename);
}

export function IssbChecklist() {
  const { entity, period, picker, error: pickError } = useEntityPeriod();
  const [data, setData] = useState<Obj | null>(null), [error, setError] = useState(""), [note, setNote] = useState(""), [busy, setBusy] = useState(false);
  const call = <T,>(fn: string, extra: Obj = {}) => governance.call<T>(fn, { governance_entity: entity, reporting_period: period, ...extra });
  const load = () => { if (!entity || !period) return; setError(""); call<Obj>("get_issb_readiness").then(setData).catch(e => { setData(null); setError(errorMessage(e)); }); };
  useEffect(load, [entity, period]);
  async function generate() { setBusy(true); setNote(""); try { const r = await call<Obj>("generate_issb_checklist"); setNote(`${num(r.created)} requirement(s) opened (${num(r.total)} in the checklist).`); load(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  async function exportIx() {
    setBusy(true); setNote("");
    try { const r = await call<Obj>("export_ixbrl"); download(btoa(unescape(encodeURIComponent(String(r.document)))), `ixbrl-${period}.xhtml`, "application/xhtml+xml"); setNote(`${num(r.facts)} fact(s) exported. ${((r.warnings as string[]) ?? []).join(" ")}`); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const rows = (data?.rows as Obj[] | undefined) ?? [], summary = (data?.summary as Obj[] | undefined) ?? [];
  return (
    <>
      {(error || pickError) && <div className="error" role="alert">{error || pickError}</div>}{note && <div className="notice" role="status">{note}</div>}
      <Card title="IFRS S1 / S2 readiness" note="Evidence is read from the GHG inventory, targets, scenario analysis, materiality and SASB responses. Narrative and sign-off stay with the disclosure owner.">
        {picker}
        <div className="gov-actions"><button type="button" className="btn primary" onClick={generate} disabled={busy || !period}>Generate checklist</button><button type="button" className="btn" onClick={exportIx} disabled={busy || !period}>Export Inline XBRL</button></div>
        {data && <div className="brc-kpis"><Kpi label="Requirements" value={num(data.requirements)} /><Kpi label="Assessed" value={num(data.assessed)} /><Kpi label="Open" value={num(data.open_items)} tone={num(data.open_items) ? "warn" : "ok"} /><Kpi label="Can state compliance" value={data.can_state_compliance ? "Yes" : "Not yet"} tone={data.can_state_compliance ? "ok" : "warn"} /></div>}
        {((data?.inconsistencies as string[] | undefined) ?? []).map(m => <div className="error" role="alert" key={m}>{m}</div>)}
      </Card>
      {summary.length > 0 && <Card title="By standard and pillar"><div className="table-wrap"><table><thead><tr><th>Standard</th><th>Pillar</th><th>Requirements</th><th>Average readiness</th><th>Ready</th></tr></thead>
        <tbody>{summary.map(s => <tr key={`${s.standard}${s.pillar}`}><td>{String(s.standard)}</td><td>{String(s.pillar)}</td><td>{num(s.requirements)}</td><td>{num(s.average_readiness)}%</td><td>{num(s.ready)}</td></tr>)}</tbody></table></div></Card>}
      {rows.length > 0 && <Card title="Requirements"><div className="table-wrap"><table><thead><tr><th>Ref</th><th>Requirement</th><th>Status</th><th>Readiness</th><th>System evidence</th></tr></thead>
        <tbody>{rows.map(r => <tr key={String(r.code)}><td>{String(r.code)}</td><td>{String(r.title)}</td><td><Tone state={String(r.status)} /></td><td>{num(r.readiness_percent)}%</td><td>{String(r.evidence || "–")}</td></tr>)}</tbody></table></div></Card>}
      {((data?.notes as string[] | undefined) ?? []).map(n => <p className="muted" key={n}>{n}</p>)}
    </>
  );
}

const STATUSES = ["Applied", "Applied in part", "Explained (not applied)", "Not applicable", "Not assessed"];
interface Practice { reference: string; requirement: string; status: string; how: string; evidence: string }
interface Principle { number: number; part: string; title: string; status: string; how: string; evidence: string; practices: Practice[] }

export function CodeAssessment() {
  const [list, setList] = useState<string[]>([]), [pick, setPick] = useState(""), [view, setView] = useState<Obj | null>(null), [open, setOpen] = useState<number | null>(null);
  const [edits, setEdits] = useState<Record<string, Partial<Practice>>>({}), [pEdits, setPEdits] = useState<Record<number, Partial<Principle>>>({}), [error, setError] = useState(""), [note, setNote] = useState("");
  useEffect(() => { api.list("Code Compliance Assessment", { fields: ["name"], limit: 100 }).then(r => { const n = r.map(x => String(x.name)); setList(n); setPick(n[0] ?? ""); }).catch(e => setError(errorMessage(e))); }, []);
  const load = (n: string) => { setError(""); setEdits({}); setPEdits({}); governance.call<Obj>("get_code_assessment", { name: n }).then(setView).catch(e => { setView(null); setError(errorMessage(e)); }); };
  useEffect(() => { if (pick) load(pick); }, [pick]);
  async function save() {
    setNote(""); setError("");
    try {
      const v = await governance.call<Obj>("save_code_assessment_answers", { name: pick,
        principles: Object.entries(pEdits).map(([number, e]) => ({ number: Number(number), ...e })), practices: Object.entries(edits).map(([reference, e]) => ({ reference, ...e })) });
      setView(v); setEdits({}); setPEdits({}); setNote("Answers saved.");
    } catch (e) { setError(errorMessage(e)); }
  }
  const s = (view?.summary as Obj | undefined) ?? {}, principles = (view?.principles as Principle[] | undefined) ?? [];
  const dirty = Object.keys(edits).length + Object.keys(pEdits).length;
  return (
    <>
      {error && <div className="error" role="alert">{error}</div>}{note && <div className="notice" role="status">{note}</div>}
      <Card title="Code assessment (apply and explain)" note="Answer each principle, then the recommended practices beneath it. A departure is always explained. Practice wording is paraphrased: read the published Code for the exact text.">
        <label>Assessment <select value={pick} onChange={e => setPick(e.target.value)}>{list.map(n => <option key={n}>{n}</option>)}</select></label>
        {list.length === 0 && <p className="muted">No assessments yet. Create one under Code Compliance Assessment.</p>}
        {view && <div className="brc-kpis"><Kpi label="Principles applied" value={`${num(s.applied)} / ${principles.length}`} /><Kpi label="Application" value={`${num(s.application_percent)}%`} tone={num(s.application_percent) >= 80 ? "ok" : "warn"} />
          <Kpi label="Practices assessed" value={`${num(s.practices_assessed)} / ${num(s.practices_in_scope)}`} /><Kpi label="Practices applied" value={`${num(s.practice_application_percent)}%`} /></div>}
        <div className="gov-actions"><button type="button" className="btn primary" onClick={save} disabled={!dirty}>Save answers{dirty ? ` (${dirty})` : ""}</button></div>
      </Card>
      {principles.map(p => {
        const pe = pEdits[p.number] ?? {}, status = pe.status ?? p.status;
        return (
          <Card key={p.number} title={`${p.number}. ${p.title}`} note={p.part}>
            <div className="gov-actions">
              <select aria-label={`Status of principle ${p.number}`} value={status} onChange={e => setPEdits({ ...pEdits, [p.number]: { ...pe, status: e.target.value } })}>{["Applied", "Applied in part", "Explained (not applied)", "Not assessed"].map(x => <option key={x}>{x}</option>)}</select>
              <input aria-label={`Evidence for principle ${p.number}`} placeholder="Evidence reference" value={pe.evidence ?? p.evidence} onChange={e => setPEdits({ ...pEdits, [p.number]: { ...pe, evidence: e.target.value } })} />
              <button type="button" className="btn" onClick={() => setOpen(open === p.number ? null : p.number)}>{open === p.number ? "Hide" : "Show"} {p.practices.length} practices</button>
            </div>
            <textarea aria-label={`Explanation for principle ${p.number}`} rows={2} placeholder="How applied, or why not" value={pe.how ?? p.how} onChange={e => setPEdits({ ...pEdits, [p.number]: { ...pe, how: e.target.value } })} />
            {open === p.number && <div className="table-wrap"><table><thead><tr><th>Ref</th><th>Recommended practice</th><th>Status</th><th>How applied, or why not</th></tr></thead><tbody>
              {p.practices.map(r => { const e = edits[r.reference] ?? {}; return (
                <tr key={r.reference}><td>{r.reference}</td><td>{r.requirement}</td>
                  <td><select aria-label={`Status of practice ${r.reference}`} value={e.status ?? r.status} onChange={ev => setEdits({ ...edits, [r.reference]: { ...e, status: ev.target.value } })}>{STATUSES.map(x => <option key={x}>{x}</option>)}</select></td>
                  <td><input aria-label={`Explanation for practice ${r.reference}`} value={e.how ?? r.how} onChange={ev => setEdits({ ...edits, [r.reference]: { ...e, how: ev.target.value } })} /></td></tr>); })}</tbody></table></div>}
          </Card>);
      })}
    </>
  );
}

export function SasbMetrics() {
  const { entity, period, picker, error: pickError } = useEntityPeriod();
  const [sum, setSum] = useState<Obj | null>(null), [error, setError] = useState(""), [note, setNote] = useState("");
  const load = () => { if (!entity || !period) return; governance.call<Obj>("get_sasb_summary", { governance_entity: entity, reporting_period: period }).then(setSum).catch(e => setError(errorMessage(e))); };
  useEffect(load, [entity, period]);
  async function template() { try { const r = await governance.call<{ filename: string; content_base64: string }>("get_sasb_template"); download(r.content_base64, r.filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"); } catch (e) { setError(errorMessage(e)); } }
  async function upload(file: File | undefined) {
    if (!file) return; setError(""); setNote("");
    try {
      const buf = new Uint8Array(await file.arrayBuffer()); let bin = ""; buf.forEach(b => { bin += String.fromCharCode(b); });
      const r = await governance.call<Obj>("import_sasb_workbook", { content_base64: btoa(bin) });
      setNote(`Industries: ${num(r.industries_created)} new, ${num(r.industries_updated)} updated. Metrics: ${num(r.metrics_created)} new, ${num(r.metrics_updated)} updated.${((r.errors as string[]) ?? []).length ? ` Skipped: ${(r.errors as string[]).join(" ")}` : ""}`);
    } catch (e) { setError(errorMessage(e)); }
  }
  async function generate() { setError(""); try { const r = await governance.call<Obj>("generate_sasb_responses", { governance_entity: entity, reporting_period: period }); setNote(`${num(r.created)} response(s) opened, ${num(r.filled_from_data_points)} filled from data points.`); load(); } catch (e) { setError(errorMessage(e)); } }
  return (
    <>
      {(error || pickError) && <div className="error" role="alert">{error || pickError}</div>}{note && <div className="notice" role="status">{note}</div>}
      <Card title="SASB industry metrics" note="SASB content is licensed, so nothing is pre-loaded. Download the template, fill it from the standard you hold, and import it. Then record which industries apply under SASB Adoption.">
        <div className="gov-actions"><button type="button" className="btn" onClick={template}>Download Excel template</button>
          <label className="btn">Import workbook<input type="file" accept=".xlsx" hidden onChange={e => upload(e.target.files?.[0])} /></label></div>
        {picker}
        <div className="gov-actions"><button type="button" className="btn primary" onClick={generate} disabled={!period}>Generate responses</button><a className="btn" href="#/app/SASB%20Adoption">SASB Adoption</a><a className="btn" href="#/app/SASB%20Metric%20Response">Answer metrics</a></div>
        {sum && <div className="brc-kpis"><Kpi label="Metrics" value={num(sum.total)} /><Kpi label="Reported" value={num(sum.Reported)} /><Kpi label="Omitted" value={num(sum.Omitted)} /><Kpi label="Not started" value={num(sum["Not started"])} tone={num(sum["Not started"]) ? "warn" : "ok"} /><Kpi label="Answered" value={`${num(sum.answered_percent)}%`} /></div>}
      </Card>
    </>
  );
}
