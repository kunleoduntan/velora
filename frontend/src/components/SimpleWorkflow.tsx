import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../api";
import { checkWorkflow, type Transition, type WState, type Workflow } from "./WorkflowBuilder";

/* The plain way to describe an approval: two tables. States say where a document can be; transitions say who moves it from one state to
   another. Anything more elaborate (conditions, parallel sign-off, named users) lives in the Advanced designer. */

const ANYONE = "__anyone__";

/** A workflow is "simple" when every transition is one role (or anyone) with no conditions, branches, quorum or named users. */
export function isSimple(w?: Workflow): boolean {
  return !w || w.transitions.every((x) => !(x.conditions?.length) && !(x.parallel_steps?.length) && !(x.users?.length) && (x.approval_mode ?? "single") === "single" && (x.roles?.length ?? 0) <= 1 && !x.rule && !(x.activities?.length));
}

/** The field that should hold the approval state: a dedicated approval field first, then the built-in Workflow State every submittable
 *  document has. Never a business status such as Document Status (Open, Completed), which the document itself maintains. */
export function pickStateField(list: { fieldname: string }[]): string {
  for (const name of ["approval_status", "workflow_state", "workflow_status"]) if (list.some((f) => f.fieldname === name)) return name;
  return list.find((f) => /(approval|workflow)/.test(f.fieldname))?.fieldname ?? "";
}

/** Quick approval: one approver (and optionally a second for the final sign-off). The person who raised it may not approve it. */
export function quickApproval(first: string, second: string): { initial: string; states: WState[]; transitions: Transition[] } {
  const states: WState[] = [{ name: "Draft" }, { name: "Pending Approval", locks_content: true }];
  const t = [row("Draft", "Pending Approval", "Send for approval")];
  if (second) {
    states.push({ name: "Pending Final Approval", locks_content: true });
    t.push(row("Pending Approval", "Pending Final Approval", "Approve", first), row("Pending Final Approval", "Approved", "Final approve", second), row("Pending Final Approval", "Rejected", "Reject", second));
  } else t.push(row("Pending Approval", "Approved", "Approve", first));
  t.push(row("Pending Approval", "Rejected", "Reject", first), row("Rejected", "Draft", "Reopen for correction"));
  states.push({ name: "Approved", is_final: true, allows_submit: true, locks_content: true }, { name: "Rejected" });
  for (const x of t) if (["Approve", "Final approve", "Reject"].includes(x.action)) x.prevent_self_approval = true;
  return { initial: "Draft", states, transitions: t };
}

function row(from_state: string, to_state: string, action = "Approve", who = ANYONE): Transition {
  return { id: `edge_${Math.random().toString(36).slice(2, 8)}`, action, label: action, from_state, to_state, roles: who === ANYONE ? [] : [who], users: [], anyone: who === ANYONE, approval_mode: "single", required_approvals: 1, conditions: [] };
}

export default function SimpleWorkflow({ workflows, selectedDoctype, onSaved, onAdvanced }: { workflows: Workflow[]; selectedDoctype: string; onSaved: () => void; onAdvanced: () => void }) {
  const existing = workflows[0];
  const [name, setName] = useState(existing?.name ?? `${selectedDoctype} Approval`);
  const [stateField, setStateField] = useState(existing?.state_field ?? "");
  const [enabled, setEnabled] = useState(existing ? !!existing.enabled : true);
  const [initial, setInitial] = useState(existing?.initial_state ?? "Draft");
  const [states, setStates] = useState<WState[]>(existing?.states ?? [{ name: "Draft" }, { name: "Pending Approval" }, { name: "Approved", is_final: true, allows_submit: true }, { name: "Rejected", is_final: true }]);
  const [transitions, setTransitions] = useState<Transition[]>(existing?.transitions ?? [row("Draft", "Pending Approval", "Send for approval"), row("Pending Approval", "Approved", "Approve", "System Manager"), row("Pending Approval", "Rejected", "Reject", "System Manager")]);
  const [roles, setRoles] = useState<string[]>([]);
  const [fields, setFields] = useState<{ fieldname: string; label: string }[]>([]);
  const [error, setError] = useState(""); const [saved, setSaved] = useState(""); const [busy, setBusy] = useState(false);

  useEffect(() => { api.knownRoles().then(setRoles).catch(() => setRoles([])); }, []);
  useEffect(() => {
    let live = true;
    api.meta(selectedDoctype).then((m: any) => {
      if (!live) return;
      const list = (m.fields || []).filter((f: any) => ["Select", "Data"].includes(f.fieldtype)).map((f: any) => ({ fieldname: f.fieldname, label: f.label || f.fieldname }));
      setFields(list);
      setStateField((cur) => cur || pickStateField(list));
    }).catch(() => setFields([]));
    return () => { live = false; };
  }, [selectedDoctype]);

  const names = states.map((s) => s.name);
  const problems = useMemo(() => checkWorkflow(initial, states, transitions), [initial, states, transitions]);
  const patchState = (i: number, p: Partial<WState>) => setStates((v) => v.map((s, j) => (j === i ? { ...s, ...p } : s)));
  const patchRow = (i: number, p: Partial<Transition>) => setTransitions((v) => v.map((x, j) => (j === i ? { ...x, ...p } : x)));
  function rename(i: number, to: string) {
    const from = states[i].name;
    patchState(i, { name: to });
    setTransitions((v) => v.map((x) => ({ ...x, from_state: x.from_state === from ? to : x.from_state, to_state: x.to_state === from ? to : x.to_state })));
    if (initial === from) setInitial(to);
  }
  function removeState(i: number) {
    const gone = states[i].name;
    setStates((v) => v.filter((_, j) => j !== i));
    setTransitions((v) => v.filter((x) => x.from_state !== gone && x.to_state !== gone));
    if (initial === gone) setInitial(states.find((_, j) => j !== i)?.name ?? "");
  }
  function addState() { let n = states.length + 1; while (names.includes(`State ${n}`)) n++; setStates((v) => [...v, { name: `State ${n}` }]); }
  const who = (x: Transition) => (x.anyone || (!x.roles.length && !x.users.length) ? ANYONE : x.roles[0]);
  function setWho(i: number, v: string) { patchRow(i, v === ANYONE ? { anyone: true, roles: [] } : { anyone: false, roles: [v] }); }

  async function save() {
    setBusy(true); setError(""); setSaved("");
    try {
      if (problems.length) throw new Error(problems[0]);
      if (!stateField && states.some((s) => s.allows_submit || s.locks_content)) throw new Error("Choose the field that holds the status, so submitting and locking can follow the state.");
      await api.saveWorkflow({
        name: name.trim() || `${selectedDoctype} Approval`, doctype: selectedDoctype, initial_state: initial, state_field: stateField || null, enabled,
        states: states.map((s) => ({ name: s.name, is_final: !!s.is_final, allows_submit: !!s.allows_submit, locks_content: !!s.locks_content, x: s.x ?? 0, y: s.y ?? 0 })),
        transitions: transitions.map((x) => ({ ...x, label: x.action, conditions: [], parallel_steps: [] })),
      });
      setSaved(enabled ? "Saved. New documents of this type now follow it." : "Saved. It is switched off."); onSaved();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  if (!isSimple(existing)) return (
    <section className="admin-card swf"><h2>This workflow uses advanced options</h2>
      <p className="muted">It has conditions, several approvers or parallel sign-off, which the simple tables cannot show without losing them. Open it in the advanced designer.</p>
      <button type="button" className="rbtn primary" onClick={onAdvanced}>Open advanced designer</button></section>);

  return (
    <section className="admin-card swf" aria-label="Simple workflow">
      <div className="swf-head"><div><h2>Approval steps</h2><p className="muted">Two tables: where a document can be, and who may move it along.</p></div>
        <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Active</label></div>
      {error && <div className="error" role="alert">{error}</div>}{saved && <div className="notice" role="status">{saved}</div>}

      <QuickSetup roles={roles} onApply={(first, second) => { const q = quickApproval(first, second); setInitial(q.initial); setStates(q.states); setTransitions(q.transitions); }} />

      <h3>1. States</h3>
      <table className="dgrid swf-table"><thead><tr><th>State</th><th>Starts here</th><th>Final</th><th>Submits document</th><th>Locks editing</th><th /></tr></thead>
        <tbody>{states.map((s, i) => (
          <tr key={i}>
            <td><input aria-label={`State ${i + 1} name`} value={s.name} onChange={(e) => rename(i, e.target.value)} /></td>
            <td className="chk"><input type="radio" name="swf-start" aria-label={`${s.name} is the start`} checked={initial === s.name} onChange={() => setInitial(s.name)} /></td>
            <td className="chk"><input type="checkbox" aria-label={`${s.name} is final`} checked={!!s.is_final} onChange={(e) => patchState(i, { is_final: e.target.checked })} /></td>
            <td className="chk"><input type="checkbox" aria-label={`${s.name} submits`} checked={!!s.allows_submit} onChange={(e) => patchState(i, { allows_submit: e.target.checked })} /></td>
            <td className="chk"><input type="checkbox" aria-label={`${s.name} locks`} checked={!!s.locks_content} onChange={(e) => patchState(i, { locks_content: e.target.checked })} /></td>
            <td><button type="button" className="rbtn" aria-label={`Remove ${s.name}`} onClick={() => removeState(i)}>Remove</button></td>
          </tr>))}</tbody></table>
      <button type="button" className="rbtn" onClick={addState}>+ Add state</button>

      <h3>2. Transitions</h3>
      <table className="dgrid swf-table"><thead><tr><th>From state</th><th>Button</th><th>To state</th><th>Who may do it</th><th /></tr></thead>
        <tbody>{transitions.map((x, i) => (
          <tr key={x.id ?? i}>
            <td><select aria-label={`Transition ${i + 1} from`} value={x.from_state} onChange={(e) => patchRow(i, { from_state: e.target.value })}>{names.map((n) => <option key={n}>{n}</option>)}</select></td>
            <td><input aria-label={`Transition ${i + 1} button`} value={x.action} onChange={(e) => patchRow(i, { action: e.target.value, label: e.target.value })} /></td>
            <td><select aria-label={`Transition ${i + 1} to`} value={x.to_state} onChange={(e) => patchRow(i, { to_state: e.target.value })}>{names.map((n) => <option key={n}>{n}</option>)}</select></td>
            <td><select aria-label={`Transition ${i + 1} who`} value={who(x)} onChange={(e) => setWho(i, e.target.value)}><option value={ANYONE}>Anyone who can open it</option>{[...new Set([...roles, ...x.roles])].map((r) => <option key={r}>{r}</option>)}</select></td>
            <td><button type="button" className="rbtn" aria-label={`Remove transition ${i + 1}`} onClick={() => setTransitions((v) => v.filter((_, j) => j !== i))}>Remove</button></td>
          </tr>))}</tbody></table>
      <button type="button" className="rbtn" onClick={() => setTransitions((v) => [...v, row(names[0] ?? "", names[1] ?? names[0] ?? "", "Approve", "System Manager")])}>+ Add transition</button>

      <div className="swf-foot">
        <label>Name <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Workflow name" /></label>
        <label>Status field <select value={stateField} onChange={(e) => setStateField(e.target.value)} aria-label="Status field"><option value="">None</option>{fields.map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label}</option>)}</select></label>
        <button type="button" className="rbtn" onClick={onAdvanced}>Advanced…</button>
        <button type="button" className="rbtn primary" disabled={busy} onClick={() => void save()}>{busy ? "Saving…" : "Save workflow"}</button>
      </div>
      {problems.length > 0 && <ul className="wf-problems" aria-label="To fix before saving">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
    </section>);
}


function QuickSetup({ roles, onApply }: { roles: string[]; onApply: (first: string, second: string) => void }) {
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  return (
    <div className="swf-quick" aria-label="Quick approval">
      <b>Quick approval:</b> approved by
      <select aria-label="First approver" value={first} onChange={(e) => setFirst(e.target.value)}><option value="">choose a role</option>{roles.map((r) => <option key={r}>{r}</option>)}</select>
      then
      <select aria-label="Second approver" value={second} onChange={(e) => setSecond(e.target.value)}><option value="">no second approval</option>{roles.map((r) => <option key={r}>{r}</option>)}</select>
      <button type="button" className="rbtn" disabled={!first} onClick={() => onApply(first, second)}>Fill the tables</button>
      <span className="muted">The person who raised a document never approves it. Adjust the tables below if you need more.</span>
    </div>);
}
