import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../api";

/* A workflow is a list of states and a list of transitions between them. This builder edits both as plain forms, so any process can be
   described, from one approver to parallel sign-offs with conditions. The picture beside it is drawn from the same data and cannot drift. */

export interface WState { name: string; is_final?: boolean; allows_submit?: boolean; locks_content?: boolean; x?: number; y?: number }
export interface Branch { key: string; label: string; roles: string[]; users: string[]; approval_mode: string; required_approvals: number }
export interface Condition { field: string; operator: string; value: unknown }
export interface Transition {
  id?: string; action: string; label?: string; from_state: string; to_state: string; roles: string[]; users: string[]; anyone?: boolean; prevent_self_approval?: boolean;
  approval_mode: string; required_approvals: number; conditions: Condition[]; condition_logic?: "all" | "any"; parallel_steps?: Branch[]; activities?: unknown[]; rule?: string;
}
export interface Workflow { name: string; doctype: string; initial_state: string; states: WState[]; transitions: Transition[]; state_field?: string | null; enabled?: number | boolean }

const OPERATORS: [string, string][] = [["=", "is"], ["!=", "is not"], [">", "is more than"], [">=", "is at least"], ["<", "is less than"], ["<=", "is at most"], ["in", "is one of"], ["not in", "is none of"]];

export const PRESETS: Record<string, { label: string; hint: string; build: (doctype: string) => Pick<Workflow, "initial_state" | "states" | "transitions"> }> = {
  single: {
    label: "One approver", hint: "Draft, then one person approves",
    build: () => ({
      initial_state: "Draft", states: [{ name: "Draft" }, { name: "Pending Approval" }, { name: "Approved", is_final: true, allows_submit: true }, { name: "Rejected", is_final: true }],
      transitions: [t("Send for approval", "Draft", "Pending Approval", { anyone: true }), t("Approve", "Pending Approval", "Approved", { roles: ["System Manager"] }), t("Reject", "Pending Approval", "Rejected", { roles: ["System Manager"] })],
    }),
  },
  two: {
    label: "Two levels", hint: "A manager, then a director",
    build: () => ({
      initial_state: "Draft", states: [{ name: "Draft" }, { name: "Manager Review" }, { name: "Director Review" }, { name: "Approved", is_final: true, allows_submit: true }, { name: "Rejected", is_final: true }],
      transitions: [t("Send for approval", "Draft", "Manager Review", { anyone: true }), t("Manager approves", "Manager Review", "Director Review", { roles: ["System Manager"] }),
        t("Director approves", "Director Review", "Approved", { roles: ["System Manager"] }), t("Reject", "Manager Review", "Rejected", { roles: ["System Manager"] }), t("Reject", "Director Review", "Rejected", { roles: ["System Manager"] })],
    }),
  },
  parallel: {
    label: "Parallel sign-off", hint: "Two departments must both agree",
    build: () => ({
      initial_state: "Draft", states: [{ name: "Draft" }, { name: "Pending Sign-off" }, { name: "Approved", is_final: true, allows_submit: true }, { name: "Rejected", is_final: true }],
      transitions: [t("Send for sign-off", "Draft", "Pending Sign-off", { anyone: true }),
        t("Sign off", "Pending Sign-off", "Approved", { parallel_steps: [{ key: "branch_1", label: "Finance", roles: ["System Manager"], users: [], approval_mode: "single", required_approvals: 1 }, { key: "branch_2", label: "Operations", roles: ["System Manager"], users: [], approval_mode: "single", required_approvals: 1 }] }),
        t("Reject", "Pending Sign-off", "Rejected", { roles: ["System Manager"] })],
    }),
  },
  amount: {
    label: "By amount", hint: "Small amounts skip the second approval",
    build: () => ({
      initial_state: "Draft", states: [{ name: "Draft" }, { name: "Pending Approval" }, { name: "Approved", is_final: true, allows_submit: true }, { name: "Rejected", is_final: true }],
      transitions: [t("Send for approval", "Draft", "Pending Approval", { anyone: true }),
        t("Approve (small)", "Pending Approval", "Approved", { roles: ["System Manager"], conditions: [{ field: "grand_total", operator: "<=", value: 100000 }] }),
        t("Approve (large)", "Pending Approval", "Approved", { roles: ["System Manager"], approval_mode: "quorum", required_approvals: 2, conditions: [{ field: "grand_total", operator: ">", value: 100000 }] }),
        t("Reject", "Pending Approval", "Rejected", { roles: ["System Manager"] })],
    }),
  },
};

function t(action: string, from_state: string, to_state: string, extra: Partial<Transition> = {}): Transition {
  return { id: `edge_${Math.random().toString(36).slice(2, 8)}`, action, label: action, from_state, to_state, roles: [], users: [], approval_mode: "single", required_approvals: 1, conditions: [], ...extra };
}

/** Problems a person should hear about before saving. */
export function checkWorkflow(initial: string, states: WState[], transitions: Transition[]): string[] {
  const out: string[] = [];
  const names = states.map((s) => s.name.trim());
  if (names.some((n) => !n)) out.push("Every state needs a name.");
  if (new Set(names).size !== names.length) out.push("State names must be different from each other.");
  if (!names.includes(initial)) out.push("Choose the state a new document starts in.");
  if (!transitions.length) out.push("Add at least one transition (a way to move between states).");
  for (const tr of transitions) {
    const who = tr.anyone || tr.roles.length || tr.users.length || (tr.parallel_steps ?? []).length;
    if (!who) out.push(`"${tr.action || "Unnamed"}" (${tr.from_state} to ${tr.to_state}) needs someone who may do it.`);
    if (tr.approval_mode === "all" && !tr.users.length) out.push(`"${tr.action}": "Everyone named" needs at least one named user.`);
  }
  const seen = new Set([initial]);
  for (let grew = true; grew;) { grew = false; for (const tr of transitions) if (seen.has(tr.from_state) && !seen.has(tr.to_state)) { seen.add(tr.to_state); grew = true; } }
  for (const s of states) if (!seen.has(s.name)) out.push(`"${s.name}" cannot be reached from "${initial}".`);
  for (const s of states) if (!s.is_final && seen.has(s.name) && !transitions.some((x) => x.from_state === s.name)) out.push(`"${s.name}" has no way out and is not marked as an end state.`);
  return out;
}

/** Layer the states left to right by distance from the start, so the picture is always tidy without dragging. */
export function layout(initial: string, states: WState[], transitions: Transition[]) {
  const depth = new Map<string, number>([[initial, 0]]);
  for (let grew = true; grew;) {
    grew = false;
    for (const tr of transitions) {
      const d = depth.get(tr.from_state);
      if (d !== undefined && !depth.has(tr.to_state)) { depth.set(tr.to_state, d + 1); grew = true; }
    }
  }
  const extra = Math.max(0, ...depth.values()) + 1;
  const columns = new Map<number, string[]>();
  for (const s of states) { const d = depth.get(s.name) ?? extra; columns.set(d, [...(columns.get(d) ?? []), s.name]); }
  const pos = new Map<string, { x: number; y: number }>();
  for (const [d, list] of columns) list.forEach((n, i) => pos.set(n, { x: 20 + d * 190, y: 20 + i * 74 }));
  const width = 20 + (Math.max(...columns.keys(), 0) + 1) * 190;
  const height = 20 + Math.max(...[...columns.values()].map((l) => l.length), 1) * 74;
  return { pos, width, height };
}

function Chips({ values, options, onChange, placeholder, label }: { values: string[]; options?: string[]; onChange: (v: string[]) => void; placeholder: string; label: string }) {
  const [text, setText] = useState("");
  const listId = useMemo(() => `chips-${Math.random().toString(36).slice(2, 8)}`, []);
  const add = (raw: string) => { const v = raw.trim(); if (v && !values.includes(v)) onChange([...values, v]); setText(""); };
  return (
    <div className="wf-chips">
      {values.map((v) => <span key={v} className="wf-chip">{v}<button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}>×</button></span>)}
      <input aria-label={label} list={options ? listId : undefined} value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(text); } }} onBlur={() => add(text)} />
      {options && <datalist id={listId}>{options.filter((o) => !values.includes(o)).map((o) => <option key={o} value={o} />)}</datalist>}
    </div>
  );
}

export default function WorkflowBuilder({ workflows, onSaved }: { workflows: Workflow[]; onSaved: () => void }) {
  const [loaded, setLoaded] = useState("");
  const [name, setName] = useState("");
  const [doctype, setDoctype] = useState("");
  const [stateField, setStateField] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [initial, setInitial] = useState("Draft");
  const [states, setStates] = useState<WState[]>([]);
  const [transitions, setTransitions] = useState<Transition[]>([]);
  const [doctypes, setDoctypes] = useState<string[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [fields, setFields] = useState<{ fieldname: string; label: string; fieldtype: string }[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.doctypes().then((r) => setDoctypes(r.map((x) => x.name).sort())).catch(() => setDoctypes([])); api.knownRoles().then(setRoles).catch(() => setRoles([])); }, []);
  useEffect(() => {
    if (!doctypes.includes(doctype)) { setFields([]); return; }
    let live = true;
    api.meta(doctype).then((m: any) => { if (live) setFields((m.fields || []).filter((f: any) => !["Section Break", "Column Break", "Tab Break", "Table"].includes(f.fieldtype)).map((f: any) => ({ fieldname: f.fieldname, label: f.label || f.fieldname, fieldtype: f.fieldtype }))); }).catch(() => live && setFields([]));
    return () => { live = false; };
  }, [doctype, doctypes]);

  const stateFieldChoices = fields.filter((f) => ["Select", "Data"].includes(f.fieldtype));
  const problems = useMemo(() => checkWorkflow(initial, states, transitions), [initial, states, transitions]);
  const picture = useMemo(() => layout(initial, states, transitions), [initial, states, transitions]);
  const stateNames = states.map((s) => s.name);

  function load(w: Workflow | undefined) {
    setSaved(""); setError("");
    if (!w) { setLoaded(""); setName(""); setDoctype(""); setStateField(""); setStates([]); setTransitions([]); setEnabled(false); setInitial("Draft"); return; }
    setLoaded(w.name); setName(w.name); setDoctype(w.doctype); setStateField(w.state_field || ""); setEnabled(w.enabled === undefined ? true : !!Number(w.enabled));
    setInitial(w.initial_state); setStates((w.states || []).map((s) => ({ ...s })));
    setTransitions((w.transitions || []).map((x, i) => ({ ...x, id: x.id || `edge_${i + 1}`, label: x.label || x.action, roles: x.roles || [], users: x.users || [], conditions: x.conditions || [], parallel_steps: x.parallel_steps || [] })));
  }
  function usePreset(key: string) {
    const p = PRESETS[key].build(doctype);
    setInitial(p.initial_state); setStates(p.states); setTransitions(p.transitions);
    if (!name) setName(`${doctype || "Document"} approval`);
    if (!stateField && stateFieldChoices.some((f) => f.fieldname === "approval_status")) setStateField("approval_status");
  }
  const patchState = (i: number, patch: Partial<WState>) => setStates((v) => v.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  function renameState(i: number, to: string) {
    const from = states[i].name;
    patchState(i, { name: to });
    setTransitions((v) => v.map((x) => ({ ...x, from_state: x.from_state === from ? to : x.from_state, to_state: x.to_state === from ? to : x.to_state })));
    if (initial === from) setInitial(to);
  }
  function addState() { let n = states.length + 1; while (stateNames.includes(`State ${n}`)) n++; setStates((v) => [...v, { name: `State ${n}` }]); if (!states.length) setInitial(`State ${n}`); }
  function removeState(i: number) {
    const gone = states[i].name;
    setStates((v) => v.filter((_, k) => k !== i)); setTransitions((v) => v.filter((x) => x.from_state !== gone && x.to_state !== gone));
    if (initial === gone) setInitial(states.find((s) => s.name !== gone)?.name ?? "");
  }
  const patchTransition = (i: number, patch: Partial<Transition>) => setTransitions((v) => v.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  const addTransition = () => setTransitions((v) => [...v, t("New action", states[0]?.name ?? "", states[1]?.name ?? states[0]?.name ?? "", { anyone: true })]);

  function patchBranch(i: number, k: number, patch: Partial<Branch>) {
    patchTransition(i, { parallel_steps: (transitions[i].parallel_steps ?? []).map((b, j) => (j === k ? { ...b, ...patch } : b)) });
  }

  async function save() {
    setBusy(true); setError(""); setSaved("");
    try {
      if (!name.trim() || !doctype.trim()) throw new Error("Give the workflow a name and choose the document type it applies to.");
      if (problems.length) throw new Error(problems[0]);
      await api.saveWorkflow({
        name: name.trim(), doctype, initial_state: initial, state_field: stateField || null, enabled,
        states: states.map((s) => ({ name: s.name, is_final: !!s.is_final, allows_submit: !!s.allows_submit, locks_content: !!s.locks_content, x: s.x ?? 0, y: s.y ?? 0 })),
        transitions: transitions.map((x) => ({ ...x, label: x.label || x.action, conditions: x.conditions.filter((c) => c.field), parallel_steps: x.parallel_steps ?? [] })),
      });
      setLoaded(name.trim()); setSaved(enabled ? "Saved. New documents of this type now follow it." : "Saved. It is switched off; tick Active when you are ready."); onSaved();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <section className="admin-card wide wf-builder" aria-label="Workflow builder">
      <div className="designer-heading">
        <div><h2>Workflow builder</h2><p className="muted">Describe the steps a document goes through and who moves it along. Approval exists only here: nothing is hard-coded.</p></div>
      </div>

      <div className="wf-grid">
        <div><label htmlFor="wf-load">Workflow</label>
          <select id="wf-load" value={loaded} onChange={(e) => load(workflows.find((w) => w.name === e.target.value))}><option value="">New workflow</option>{workflows.map((w) => <option key={w.name}>{w.name}</option>)}</select></div>
        <div><label htmlFor="wf-name">Name</label><input id="wf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Purchase Invoice approval" /></div>
        <div><label htmlFor="wf-doctype">Applies to</label><input id="wf-doctype" list="wf-doctypes" value={doctype} onChange={(e) => setDoctype(e.target.value)} placeholder="Choose a document type" /><datalist id="wf-doctypes">{doctypes.map((n) => <option key={n} value={n} />)}</datalist></div>
        <div><label htmlFor="wf-field">Keep the state in field</label>
          <select id="wf-field" value={stateField} onChange={(e) => setStateField(e.target.value)}><option value="">(choose a field)</option>{stateFieldChoices.map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label}</option>)}</select></div>
        <div className="wf-active"><label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Active: documents follow this workflow</label></div>
      </div>

      <div className="wf-presets"><span className="muted">Start from:</span>{Object.entries(PRESETS).map(([k, p]) => <button key={k} type="button" className="rbtn" title={p.hint} onClick={() => usePreset(k)}>{p.label}</button>)}</div>

      <h3>1. States <small className="muted">where a document can be</small></h3>
      <table className="dgrid wf-table"><thead><tr><th>Name</th><th>Starts here</th><th>Can be submitted here</th><th>Locks editing</th><th>End of process</th><th /></tr></thead>
        <tbody>{states.map((s, i) => (
          <tr key={i}>
            <td><input aria-label={`State ${i + 1} name`} value={s.name} onChange={(e) => renameState(i, e.target.value)} /></td>
            <td><input type="radio" name="wf-initial" aria-label={`${s.name} is the starting state`} checked={initial === s.name} onChange={() => setInitial(s.name)} /></td>
            <td><input type="checkbox" aria-label={`${s.name} allows submit`} checked={!!s.allows_submit} onChange={(e) => patchState(i, { allows_submit: e.target.checked })} /></td>
            <td><input type="checkbox" aria-label={`${s.name} locks editing`} checked={!!s.locks_content} onChange={(e) => patchState(i, { locks_content: e.target.checked })} /></td>
            <td><input type="checkbox" aria-label={`${s.name} ends the process`} checked={!!s.is_final} onChange={(e) => patchState(i, { is_final: e.target.checked })} /></td>
            <td><button type="button" className="rbtn danger" aria-label={`Delete state ${s.name}`} onClick={() => removeState(i)}>Delete</button></td>
          </tr>))}</tbody></table>
      <button type="button" className="rbtn" onClick={addState}>+ Add state</button>

      <h3>2. Transitions <small className="muted">who may move a document from one state to another</small></h3>
      {transitions.map((x, i) => (
        <fieldset key={x.id ?? i} className="wf-transition" aria-label={`Transition ${i + 1}`}>
          <div className="wf-row">
            <select aria-label={`Transition ${i + 1} from`} value={x.from_state} onChange={(e) => patchTransition(i, { from_state: e.target.value })}>{stateNames.map((n) => <option key={n}>{n}</option>)}</select>
            <span aria-hidden="true">→</span>
            <input aria-label={`Transition ${i + 1} action`} value={x.action} onChange={(e) => patchTransition(i, { action: e.target.value, label: e.target.value })} placeholder="Button name, e.g. Approve" />
            <span aria-hidden="true">→</span>
            <select aria-label={`Transition ${i + 1} to`} value={x.to_state} onChange={(e) => patchTransition(i, { to_state: e.target.value })}>{stateNames.map((n) => <option key={n}>{n}</option>)}</select>
            <button type="button" className="rbtn danger" aria-label={`Delete transition ${i + 1}`} onClick={() => setTransitions((v) => v.filter((_, k) => k !== i))}>Delete</button>
          </div>

          <div className="wf-who">
            <label className="check"><input type="checkbox" checked={!!x.anyone} onChange={(e) => patchTransition(i, { anyone: e.target.checked })} /> Anyone who can open the document</label>
            {!x.anyone && <>
              <div><span>Roles</span><Chips label={`Transition ${i + 1} roles`} values={x.roles} options={roles} placeholder="Add a role, press Enter" onChange={(roles_) => patchTransition(i, { roles: roles_ })} /></div>
              <div><span>Named people</span><Chips label={`Transition ${i + 1} users`} values={x.users} placeholder="Add an email, press Enter" onChange={(users) => patchTransition(i, { users })} /></div>
            </>}
            <label className="check"><input type="checkbox" checked={!!x.prevent_self_approval} onChange={(e) => patchTransition(i, { prevent_self_approval: e.target.checked })} /> The person who created the document cannot do this</label>
          </div>

          <div className="wf-row">
            <label>How many must agree
              <select aria-label={`Transition ${i + 1} approval mode`} value={x.approval_mode === "any" ? "single" : x.approval_mode} onChange={(e) => patchTransition(i, { approval_mode: e.target.value })}>
                <option value="single">One person</option><option value="quorum">A number of people</option><option value="all">Every named person</option></select></label>
            {x.approval_mode === "quorum" && <label>How many<input type="number" min={1} max={100} aria-label={`Transition ${i + 1} approvals needed`} value={x.required_approvals} onChange={(e) => patchTransition(i, { required_approvals: Math.max(1, Number(e.target.value) || 1) })} /></label>}
          </div>

          <div className="wf-conditions">
            <div className="wf-row"><strong>Only when</strong>
              {x.conditions.length > 1 && <select aria-label={`Transition ${i + 1} condition logic`} value={x.condition_logic ?? "all"} onChange={(e) => patchTransition(i, { condition_logic: e.target.value as "all" | "any" })}><option value="all">all of these are true</option><option value="any">any of these is true</option></select>}
              {!x.conditions.length && <span className="muted">always</span>}</div>
            {x.conditions.map((c, k) => (
              <div className="wf-row" key={k}>
                <select aria-label={`Transition ${i + 1} condition ${k + 1} field`} value={c.field} onChange={(e) => patchTransition(i, { conditions: x.conditions.map((y, j) => (j === k ? { ...y, field: e.target.value } : y)) })}>
                  <option value="">(field)</option>{fields.map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label}</option>)}</select>
                <select aria-label={`Transition ${i + 1} condition ${k + 1} operator`} value={c.operator} onChange={(e) => patchTransition(i, { conditions: x.conditions.map((y, j) => (j === k ? { ...y, operator: e.target.value } : y)) })}>{OPERATORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                <input aria-label={`Transition ${i + 1} condition ${k + 1} value`} value={Array.isArray(c.value) ? c.value.join(", ") : String(c.value ?? "")}
                  onChange={(e) => patchTransition(i, { conditions: x.conditions.map((y, j) => (j === k ? { ...y, value: castValue(e.target.value, y.operator, fields.find((f) => f.fieldname === y.field)?.fieldtype) } : y)) })} />
                <button type="button" className="rbtn" aria-label={`Remove condition ${k + 1}`} onClick={() => patchTransition(i, { conditions: x.conditions.filter((_, j) => j !== k) })}>Remove</button>
              </div>))}
            <button type="button" className="rbtn" onClick={() => patchTransition(i, { conditions: [...x.conditions, { field: fields[0]?.fieldname ?? "", operator: "=", value: "" }] })}>+ Add condition</button>
          </div>

          <div className="wf-branches">
            <strong>Parallel sign-off</strong> <span className="muted">(every group below must agree before the document moves)</span>
            {(x.parallel_steps ?? []).map((b, k) => (
              <div className="wf-row" key={b.key}>
                <input aria-label={`Transition ${i + 1} group ${k + 1} name`} value={b.label} placeholder="Group, e.g. Finance" onChange={(e) => patchBranch(i, k, { label: e.target.value })} />
                <Chips label={`Transition ${i + 1} group ${k + 1} roles`} values={b.roles} options={roles} placeholder="Roles" onChange={(r) => patchBranch(i, k, { roles: r })} />
                <select aria-label={`Transition ${i + 1} group ${k + 1} mode`} value={b.approval_mode === "any" ? "single" : b.approval_mode} onChange={(e) => patchBranch(i, k, { approval_mode: e.target.value })}><option value="single">One person</option><option value="quorum">A number</option></select>
                {b.approval_mode === "quorum" && <input type="number" min={1} aria-label={`Transition ${i + 1} group ${k + 1} count`} value={b.required_approvals} onChange={(e) => patchBranch(i, k, { required_approvals: Math.max(1, Number(e.target.value) || 1) })} />}
                <button type="button" className="rbtn" aria-label={`Remove group ${k + 1}`} onClick={() => patchTransition(i, { parallel_steps: (x.parallel_steps ?? []).filter((_, j) => j !== k) })}>Remove</button>
              </div>))}
            <button type="button" className="rbtn" onClick={() => patchTransition(i, { parallel_steps: [...(x.parallel_steps ?? []), { key: `branch_${Date.now() % 100000}_${(x.parallel_steps ?? []).length}`, label: "", roles: [], users: [], approval_mode: "single", required_approvals: 1 }] })}>+ Add group</button>
          </div>
        </fieldset>))}
      <button type="button" className="rbtn" onClick={addTransition} disabled={states.length < 2}>+ Add transition</button>

      {states.length > 0 && <>
        <h3>3. The flow <small className="muted">drawn from the steps above</small></h3>
        <div className="wf-picture" role="img" aria-label="Workflow diagram">
          <svg width={picture.width} height={picture.height}>
            <defs><marker id="wf-arrow" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="currentColor" /></marker></defs>
            {transitions.map((x, i) => {
              const a = picture.pos.get(x.from_state), b = picture.pos.get(x.to_state);
              if (!a || !b) return null;
              const x1 = a.x + 150, y1 = a.y + 22, x2 = b.x, y2 = b.y + 22, same = a.x === b.x;
              const d = same ? `M${a.x + 75},${a.y + 44} C${a.x + 75},${a.y + 70} ${b.x + 75},${b.y - 26} ${b.x + 75},${b.y}` : `M${x1},${y1} C${x1 + 20},${y1} ${x2 - 20},${y2} ${x2},${y2}`;
              return <g key={i}><path d={d} fill="none" stroke="currentColor" strokeWidth="1.4" markerEnd="url(#wf-arrow)" /><text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4} fontSize="10" textAnchor="middle" fill="currentColor">{x.action}</text></g>;
            })}
            {states.map((s) => { const p = picture.pos.get(s.name); return p ? <g key={s.name}><rect x={p.x} y={p.y} width="150" height="44" rx="8" fill="var(--card)" stroke={s.name === initial ? "var(--brand)" : "currentColor"} strokeWidth={s.name === initial ? 2.5 : 1.2} /><text x={p.x + 75} y={p.y + 26} textAnchor="middle" fontSize="12" fill="currentColor">{s.name}{s.is_final ? " ■" : ""}</text></g> : null; })}
          </svg>
        </div>
      </>}

      {problems.length > 0 && states.length > 0 && <ul className="wf-problems" aria-label="To fix before saving">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      {error && <div className="error" role="alert">{error}</div>}
      {saved && <div className="success" role="status">{saved}</div>}
      <div className="wf-save"><button type="button" className="rbtn primary" disabled={busy} onClick={() => void save()}>{busy ? "Saving…" : "Save workflow"}</button></div>
    </section>
  );
}

function castValue(raw: string, operator: string, fieldtype?: string): unknown {
  if (operator === "in" || operator === "not in") return raw.split(",").map((x) => x.trim()).filter(Boolean);
  if (["Int", "Float", "Currency", "Percent"].includes(fieldtype ?? "") && raw.trim() !== "" && !Number.isNaN(Number(raw))) return Number(raw);
  return raw;
}
