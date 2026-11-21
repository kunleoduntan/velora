import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import SettlementDialog from "./SettlementDialog";
import ProfilePhoto from "./ProfilePhoto";
import PullItemsDialog from "./PullItemsDialog";
import FlowOptionsDialog, { FLOW_OPTIONS } from "./FlowOptionsDialog";
import ApplyInvoicesDialog from "./ApplyInvoicesDialog";
import CancelDialog from "./CancelDialog";
import { api, type CopyPayload, type DocumentFlowAction, errorMessage, getCompany, getProfile } from "../api";
import { loadScripts, trigger, velora, type FormApi } from "../clientScripts";
import { buildLayout } from "../layout";
import { navigate } from "../router";
import Icon from "../ui/Icon";
import type { Doc, Field, Meta } from "../types";
import FieldControl from "./FieldControl";
import { evaluateCondition, type ConditionContext } from "../conditions";
import GridForm from "./GridForm";
import AttachmentPanel from "./AttachmentPanel";
import DocumentTimeline from "./DocumentTimeline";
import WorkflowBar from "./WorkflowBar";
import { getFormComponent } from "../customForms";
import { fetchedValues } from "../fetchFrom";

interface UiState {
  buttons: { label: string; fn: () => void }[];
  intro: string;
  readOnly: Record<string, boolean>;
  hidden: Record<string, boolean>;
}

function initialValue(f: Field): unknown {
  if (f.fieldtype === "Table") return [];
  if (f.fieldtype === "Check") return f.default ? 1 : 0;
  if (f.default === "Today") return new Date().toISOString().slice(0, 10);
  if (f.default === "Now") return new Date().toISOString().slice(0, 16);
  return f.default ?? null;
}

function newDoc(meta: Meta): Doc {
  const d: Doc = { doctype: meta.name, docstatus: 0 };
  for (const f of meta.fields) if (!["Section Break", "Column Break", "Tab Break"].includes(f.fieldtype)) d[f.fieldname] = initialValue(f);
  return d;
}

const STATUS = ["Draft", "Submitted", "Cancelled"];

/** 12-column business form grid: field width follows the expected data shape, not an arbitrary two-column split. */
export function fieldGridSpan(field: Field): number {
  const type = field.fieldtype;
  const key = `${field.fieldname} ${field.label || ""}`.toLowerCase();
  if (["Table", "Text", "Long Text", "JSON"].includes(type)) return 12;
  if (type === "Small Text" || type === "Code") return 6;
  if (type === "Date") return 3;
  if (type === "Datetime") return 4;
  if (["Int", "Float", "Currency", "Percent", "Check"].includes(type)) return 3;
  if (type === "Link" || type === "Select") return 4;
  if (type === "Email" || type === "Phone") return 4;
  if (/(description|address|remarks|comment|narration|purpose|notes|details|message)/.test(key)) return 8;
  if (/(name|title|subject|reference|number|code)/.test(key)) return 5;
  return 4;
}

/** Duplicate and Amend open a NEW, UNSAVED form pre-filled from the server's copy (the server decides what may be copied). It is handed over through sessionStorage, once. */
export const PREFILL_KEY = "velora.prefill";
function takePrefill(doctype: string): CopyPayload | null {
  try {
    const raw = sessionStorage.getItem(PREFILL_KEY);
    sessionStorage.removeItem(PREFILL_KEY);
    const p = raw ? (JSON.parse(raw) as CopyPayload) : null;
    return p && p.doctype === doctype ? p : null;
  } catch { return null; }
}

export default function FormView({ doctype, name }: { doctype: string; name: string }) {
  const isNew = name === "new";
  const [meta, setMeta] = useState<Meta | null>(null);
  const [childMetas, setChildMetas] = useState<Record<string, Meta>>({});
  const [doc, setDoc] = useState<Doc | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [invalid, setInvalid] = useState<string[]>([]);
  const [tabIdx, setTabIdx] = useState(0);
  const [copied, setCopied] = useState<CopyPayload | null>(null);
  const [amendedTo, setAmendedTo] = useState<string | null>(null);
  const [createFromActions, setCreateFromActions] = useState<DocumentFlowAction[]>([]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [, force] = useReducer((x: number) => x + 1, 0);
  const [reloadTick, setReloadTick] = useState(0);
  const [wfGate, setWfGate] = useState<{ waiting: boolean; locked: boolean }>({ waiting: false, locked: false });
  useEffect(() => { let live = true; api.pullSources(doctype).then((r) => { if (live) setPullSources(r); }).catch(() => { if (live) setPullSources([]); }); return () => { live = false; }; }, [doctype]);
  useEffect(() => { const on = () => setReloadTick((n) => n + 1); window.addEventListener("velora:reload", on); return () => window.removeEventListener("velora:reload", on); }, []);

  const docRef = useRef<Doc | null>(null);
  const metaRef = useRef<Meta | null>(null);
  const isNewRef = useRef(isNew);
  const ui = useRef<UiState>({ buttons: [], intro: "", readOnly: {}, hidden: {} });
  const active = useRef(new Set<string>()); // guards against a handler re-triggering its own event

  const frm = useMemo<FormApi>(() => ({
    get doc() { return docRef.current as Doc; },
    get meta() { return metaRef.current as Meta; },
    is_new: () => isNewRef.current,
    set_value(fieldname, value) {
      docRef.current = { ...docRef.current!, [fieldname]: value };
      setDoc(docRef.current);
      setDirty(true);
      setInvalid((cur) => cur.filter((f) => f !== fieldname));
      if (!active.current.has(fieldname)) {
        active.current.add(fieldname);
        try { trigger(metaRef.current!.name, fieldname, frm); } finally { active.current.delete(fieldname); }
      }
      force();
      void fetchedValues(metaRef.current!, fieldname, value).then((extra) => {      // ERPNext-style fetch from the linked document
        if (!Object.keys(extra).length || docRef.current?.[fieldname] !== value) return;
        docRef.current = { ...docRef.current!, ...extra };
        setDoc(docRef.current); force();
      });
    },
    add_table_row(table, row = {}) {
      const rows = Array.isArray(docRef.current?.[table]) ? docRef.current![table] as Record<string, unknown>[] : [];
      docRef.current = { ...docRef.current!, [table]: [...rows, { ...row }] };
      setDoc(docRef.current); setDirty(true); force();
    },
    set_table_value(table, rowIndex, fieldname, value) {
      const rows = Array.isArray(docRef.current?.[table]) ? docRef.current![table] as Record<string, unknown>[] : [];
      if (rowIndex < 0 || rowIndex >= rows.length) return;
      const nextRows = rows.map((row, index) => index === rowIndex ? { ...row, [fieldname]: value } : row);
      docRef.current = { ...docRef.current!, [table]: nextRows };
      setDoc(docRef.current); setDirty(true); force();
    },
    get_row_prices(args) { return api.documentPricing(metaRef.current!.name, args); },
    add_button: (label, fn) => { ui.current.buttons.push({ label, fn }); },
    set_intro: (m) => { ui.current.intro = m; },
    set_read_only: (f, ro = true) => { ui.current.readOnly[f] = ro; force(); },
    toggle_hidden: (f, h = true) => { ui.current.hidden[f] = h; force(); },
  }), []);

  function refresh() {
    ui.current.buttons = [];
    ui.current.intro = "";
    trigger(metaRef.current!.name, "refresh", frm);
    force();
  }

  // ---- load meta + child metas + scripts + document --------------------------------------
  useEffect(() => {
    let cancelled = false;
    isNewRef.current = isNew;
    setMeta(null); setDoc(null); setError(""); setDirty(false); setInvalid([]); setTabIdx(0); setCreateFromActions([]);
    ui.current = { buttons: [], intro: "", readOnly: {}, hidden: {} };
    (async () => {
      try {
        const m = await api.meta(doctype);
        const cms: Record<string, Meta> = {};
        for (const f of m.fields) if (f.fieldtype === "Table") cms[String(f.options)] = await api.meta(String(f.options));
        await loadScripts(doctype, "form");
        const pre = isNew ? takePrefill(doctype) : null;
        const d = isNew ? { ...newDoc(m), ...(pre?.values ?? {}) } : await api.get(doctype, name);
        if (cancelled) return;
        metaRef.current = m; docRef.current = d;
        setMeta(m); setChildMetas(cms); setDoc(d); setCopied(pre); setAmendedTo(null);
        if (pre) setDirty(true);                                                       // pre-filled but not saved yet
        if (!isNew && m.is_submittable && Number(d.docstatus) === 2) api.amendedTo(doctype, name).then((r) => { if (!cancelled) setAmendedTo(r.amended_to); }).catch(() => {});
        refresh();
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doctype, name, reloadTick]);

  useEffect(() => {
    let cancelled = false;
    if (isNew) { setCreateFromActions([]); return; }  // the server decides which actions fit this document now (submitted, draft or open, and its status)
    api.documentFlowActions(doctype, name)
      .then((actions) => { if (!cancelled) setCreateFromActions(actions.filter((action) => action.available)); })
      .catch(() => { if (!cancelled) setCreateFromActions([]); });
    return () => { cancelled = true; };
  }, [doctype, name, isNew, doc?.docstatus, (doc as any)?.request_status, (doc as any)?.status, (doc as any)?.transit_status]);

  const layout = useMemo(() => (meta ? buildLayout(meta.fields) : []), [meta]);
  const CustomForm = getFormComponent(doctype);
  const fieldMap = useMemo(() => Object.fromEntries((meta?.fields ?? []).map((f) => [f.fieldname, f])), [meta]);
  const conditionContext = useMemo<ConditionContext>(() => {
    const prof = getProfile();
    const co = prof?.companies.find((c) => c.id === getCompany());
    return { user: prof?.user.email ?? null, roles: co?.roles ?? [], islocal: isNew };
  }, [isNew]);
  const conditionalState = useMemo(() => {
    const hidden: Record<string, boolean> = {};
    const required: Record<string, boolean> = {};
    const readOnly: Record<string, boolean> = {};
    for (const f of meta?.fields ?? []) {
      hidden[f.fieldname] = Boolean(f.hidden) || Boolean(f.depends_on && !evaluateCondition(f.depends_on, doc ?? {}, conditionContext));
      required[f.fieldname] = Boolean(f.required) || Boolean(f.mandatory_depends_on && evaluateCondition(f.mandatory_depends_on, doc ?? {}, conditionContext));
      readOnly[f.fieldname] = Boolean(f.read_only) || Boolean(f.read_only_depends_on && evaluateCondition(f.read_only_depends_on, doc ?? {}, conditionContext));
    }
    return { hidden, required, readOnly };
  }, [meta, doc, conditionContext]);

  const [settle, setSettle] = useState<DocumentFlowAction | null>(null);
  const [flowOpts, setFlowOpts] = useState<DocumentFlowAction | null>(null);
  const [applyOpen, setApplyOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [pullFrom, setPullFrom] = useState<string | null>(null);
  const [pullSources, setPullSources] = useState<string[]>([]);
  const [pullMenu, setPullMenu] = useState(false);
  const [createMenu, setCreateMenu] = useState(false);
  if (!meta || !doc) return <div className="panel">{error ? <div className="error">{error}</div> : "Loading…"}</div>;

  const perms = meta.permissions;
  const docstatus = Number(doc.docstatus ?? 0);
  const formReadOnly = isNew ? !perms.create : docstatus !== 0 || !perms.write;
  const title = isNew ? `New ${doctype}` : String((meta.title_field && doc[meta.title_field]) || doc.name);
  const pill = isNew ? "Not Saved" : dirty ? "Not Saved" : meta.is_submittable ? STATUS[docstatus] : "Saved";

  const payload = () => ({ ...docRef.current! });


  async function startCopy(mode: "amend" | "duplicate") {
    setError("");
    try {
      const p = await api.copyDoc(doctype, name, mode);
      sessionStorage.setItem(PREFILL_KEY, JSON.stringify(p));
      window.location.hash = `#/app/${encodeURIComponent(doctype)}/new`;
    } catch (e) { setError(errorMessage(e)); }                                       // e.g. "already amended as X"
  }

  async function run(fn: () => Promise<Doc | void>) {
    setBusy(true); setError("");
    try {
      const out = await fn();
      if (out) { docRef.current = out; setDoc(out); setDirty(false); refresh(); }
    } catch (e) {
      setError(errorMessage(e));
    } finally { setBusy(false); }
  }

  async function save(andNew = false) {
    const missing = meta!.fields.filter((f) => conditionalState.required[f.fieldname] && !conditionalState.hidden[f.fieldname] && !["Section Break", "Column Break", "Tab Break"].includes(f.fieldtype))
      .filter((f) => { const v = docRef.current![f.fieldname]; return v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length); })
      .map((f) => f.fieldname);
    setInvalid(missing);
    if (missing.length) {
      return setError(`Missing required: ${missing.map((m) => meta!.fields.find((f) => f.fieldname === m)!.label).join(", ")}`);
    }
    try { trigger(doctype, "validate", frm, true); } catch (e) { return setError(errorMessage(e)); }
    const newHash = `#/app/${encodeURIComponent(doctype)}/new`;
    await run(async () => {
      if (isNew) {
        const saved = await api.create(doctype, payload());
        navigate(doctype, String(saved.name));
        if (andNew) setTimeout(() => { window.location.hash = newHash; }, 60);      // leave "new" first so the blank form really resets
        return saved;
      }
      const updated = await api.update(doctype, name, payload());
      if (andNew) window.location.hash = newHash;
      return updated;
    });
  }

  const act = (a: "submit") => run(() => api.action(doctype, name, a));
  /** Add what Get Items From returned: fill empty header fields, replace blank rows, append the pulled lines. */
  function applyPulled(r: { header: Record<string, unknown>; lines: Record<string, unknown>[] }) {
    const tableField = meta?.fields.find((f) => f.fieldtype === "Table" && f.fieldname === "lines") ?? meta?.fields.find((f) => f.fieldtype === "Table");
    if (!tableField) return;
    const child = childMetas[String(tableField.options)];
    const numeric = new Set((child?.fields ?? []).filter((f) => ["Float", "Int", "Currency"].includes(f.fieldtype)).map((f) => f.fieldname));
    const rows = r.lines.map((row) => Object.fromEntries(Object.entries(row).map(([k, v]) => [k, numeric.has(k) && v !== null && v !== "" ? Number(v) : v])));
    for (const [k, v] of Object.entries(r.header)) if (v !== null && v !== undefined && !docRef.current?.[k]) frm.set_value(k, v);
    const existing = (Array.isArray(docRef.current?.[tableField.fieldname]) ? docRef.current![tableField.fieldname] as Record<string, unknown>[] : []).filter((row) => row.item_code || row.description);
    frm.set_value(tableField.fieldname, [...existing, ...rows]);
  }
  async function createFrom(action: DocumentFlowAction, overrides: Record<string, unknown> = {}) {
    if (dirty) { setError("Save or discard your changes before creating a follow-on document."); return; }
    if (!("__asked" in overrides) && FLOW_OPTIONS[`${action.source_doctype}:${action.target_doctype}`]) { setFlowOpts(action); return; }
    overrides = Object.fromEntries(Object.entries(overrides).filter(([k]) => k !== "__asked"));
    if ((action.target_doctype === "Receipt" || action.target_doctype === "Payment") && !("bank_account" in overrides)) { setSettle(action); return; }
    setBusy(true); setError("");
    try {
      const created = await api.createFromDocument(doctype, name, action.target_doctype, overrides);
      navigate(created.doctype, created.name);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  const remove = () => {
    if (!window.confirm(`Move draft ${doctype} ${name} to the Deleted Documents inbox?`)) return;
    const reason=window.prompt("Enter the reason for deleting this draft:");
    if(reason===null)return;
    if(!reason.trim()){window.alert("A deletion reason is required.");return;}
    return run(async () => { await api.remove(doctype, name, reason.trim()); navigate(doctype); });
  };

  return (
    <div className="form-view">
      {cancelOpen && <CancelDialog doctype={doctype} name={name} onClose={() => setCancelOpen(false)} onDone={() => { setCancelOpen(false); setReloadTick((n) => n + 1); }} />}
      {applyOpen && (doctype === "Receipt" || doctype === "Payment") && (
        <ApplyInvoicesDialog kind={doctype} partyType={doctype === "Receipt" ? "Customer" : "Supplier"} currency={String(doc.currency ?? "")} reference={String(doc.narration ?? "")}
          initialAmount={Number(doc.total_amount ?? 0)}
          onCancel={() => setApplyOpen(false)}
          onApply={(lines) => { setApplyOpen(false); frm.set_value("lines", lines); }} />)}
      {pullFrom && doc && <PullItemsDialog target={doctype} source={pullFrom} party={String(doc.party ?? "")} onCancel={() => setPullFrom(null)} onPull={(r) => { setPullFrom(null); applyPulled(r); }} />}
      {flowOpts && <FlowOptionsDialog title={flowOpts.label} options={FLOW_OPTIONS[`${flowOpts.source_doctype}:${flowOpts.target_doctype}`]}
        onCancel={() => setFlowOpts(null)} onConfirm={(values) => { const a = flowOpts; setFlowOpts(null); void createFrom(a, { ...values, __asked: true }); }} />}
      {settle && <SettlementDialog kind={settle.target_doctype as "Receipt" | "Payment"} title={settle.label} invoiceTotal={Math.max(0, Number(doc?.grand_total ?? 0) - Number(doc?.amount_settled ?? 0))}
        onCancel={() => setSettle(null)}
        onConfirm={(bank_account, settlement_amount) => { const a = settle; setSettle(null); void createFrom(a, { bank_account, settlement_amount }); }} />}
      {meta.image_field && (
        <ProfilePhoto doctype={doctype} name={isNew ? null : name} imageId={String(doc[meta.image_field] ?? "")} title={title}
          canWrite={!formReadOnly} onChange={(id) => frm.set_value(meta.image_field as string, id)} />)}
      <header className="page-head">
        <div className="doc-context"><a className="rbtn" href={`#/app/${encodeURIComponent(doctype)}`} title={`Back to the ${doctype} list`}><span>← {doctype} list</span></a><span className="doc-chip" title="The document type you are working in">{doctype}</span></div>
        <div className="titles">
          <h1>{title}</h1>
          {!isNew && <span className="muted">{String(doc.name)}</span>}
          <span className={`pill pill-${pill.toLowerCase().replace(" ", "-")}`}>{pill}</span>
        </div>
      </header>
      <div className="ribbon" role="toolbar" aria-label="Actions">
        {createFromActions.length > 0 && (
          <span className="menu-wrap"><button type="button" className="rbtn primary" aria-haspopup="menu" aria-expanded={createMenu} disabled={busy || dirty} title={dirty ? "Save first, then create the next document from this one" : "Create the next document from this one"} onClick={() => setCreateMenu((v) => !v)}><Icon name="plus" /><span>Create</span><Icon name="down" size={12} /></button>
            {createMenu && <div className="menu" role="menu" onMouseLeave={() => setCreateMenu(false)}>{createFromActions.map((action) => <button key={`${action.source_doctype}:${action.target_doctype}`} type="button" role="menuitem" title={action.description} onClick={() => { setCreateMenu(false); void createFrom(action); }}>{action.label}</button>)}</div>}</span>)}
        {createFromActions.length > 0 && <span className="rsep" />}
        {!formReadOnly && docstatus === 0 && ((doctype === "Receipt" && doc.purpose === "Customer Receipt") || (doctype === "Payment" && (doc.purpose === "Supplier Payment" || doc.purpose === "Expense Payment"))) &&
          <button type="button" className="rbtn" disabled={busy} title="Fetch the party's open invoices and allocate this amount across them" onClick={() => setApplyOpen(true)}><Icon name="copy" /><span>Apply to Invoices</span></button>}
        {!formReadOnly && docstatus === 0 && pullSources.length > 0 && (
          <span className="menu-wrap"><button type="button" className="rbtn" aria-haspopup="menu" aria-expanded={pullMenu} onClick={() => setPullMenu((v) => !v)} title="Add items from open orders, receipts or deliveries"><Icon name="copy" /><span>Get Items From</span></button>
            {pullMenu && <div className="menu" role="menu">{pullSources.map((src) => <button key={src} type="button" role="menuitem" onClick={() => { setPullMenu(false); setPullFrom(src); }}>{src}</button>)}</div>}</span>)}
        {!formReadOnly && <button type="button" className="rbtn primary" disabled={busy} onClick={() => save()}><Icon name="save" /><span>Save</span></button>}
        {!formReadOnly && !meta.istable && perms.create && docstatus === 0 && <button type="button" className="rbtn" disabled={busy} onClick={() => save(true)} title="Save this record and open a blank one"><Icon name="save" /><span>Save &amp; New</span></button>}
        {!isNew && meta.is_submittable && docstatus === 0 && perms.submit && !dirty &&
          <button type="button" className="rbtn" disabled={busy || wfGate.waiting} title={wfGate.waiting ? "Waiting for approval: this can be submitted once the approval workflow approves it" : undefined} onClick={() => act("submit")}><Icon name="submit" /><span>Submit</span></button>}
        {!isNew && meta.is_submittable && docstatus === 1 && perms.cancel &&
          <button type="button" className="rbtn" disabled={busy} onClick={() => setCancelOpen(true)}><Icon name="ban" /><span>Cancel</span></button>}
        {!isNew && perms.delete && docstatus !== 1 &&
          <button type="button" className="rbtn danger" disabled={busy} onClick={remove}><Icon name="trash" /><span>Delete</span></button>}
        {!isNew && meta.is_submittable && docstatus === 2 && perms.create && !amendedTo &&
          <button type="button" className="rbtn primary" disabled={busy} onClick={() => startCopy("amend")}><Icon name="copy" /><span>Amend</span></button>}
        {!isNew && perms.share && <button type="button" className="rbtn" disabled={busy} onClick={async () => { const email=window.prompt("Share this record with user email:"); if(email) { try { await api.shareDocument(doctype,name,{email,read:true,write:false}); window.alert("Record shared."); } catch(e) { window.alert(errorMessage(e)); } } }}><Icon name="users"/><span>Share</span></button>}
        {!isNew && perms.email && <button type="button" className="rbtn" disabled={busy} onClick={async () => { const recipient=window.prompt("Recipient email:"); if(recipient) { const message=window.prompt("Message (optional):") || ""; try { await api.emailDocument(doctype,name,{recipient,message}); window.alert("Email sent."); } catch(e) { window.alert(errorMessage(e)); } } }}><Icon name="mail"/><span>Email</span></button>}
        {!isNew && perms.print && <button type="button" className="rbtn" disabled={busy} onClick={async () => { const win=window.open("about:blank","_blank"); try { const fmts=await api.printFormatsFor(doctype); if(!fmts.length) { win?.close(); window.alert("No print format is configured for this DocType."); return; } const chosen=fmts.length===1?fmts[0]:fmts.find((f:any)=>f.name===window.prompt(`Choose print format:\n${fmts.map((f:any)=>f.name).join("\n")}`)); if(!chosen) { win?.close(); return; } if(win) win.location.href=`/api/print/${encodeURIComponent(chosen.id)}/${encodeURIComponent(doctype)}/${encodeURIComponent(name)}`; } catch(e) { win?.close(); window.alert(errorMessage(e)); } }}><Icon name="printer"/><span>Print</span></button>}
        {!isNew && !meta.istable && perms.create &&
          <button type="button" className="rbtn" disabled={busy} onClick={() => startCopy("duplicate")}><Icon name="copy" /><span>Duplicate</span></button>}
        {meta.can_customize && !meta.istable && <a className="rbtn" href={`#/settings/layout/${encodeURIComponent(doctype)}`}><Icon name="cog" /><span>Customize form</span></a>}
        {ui.current.buttons.length > 0 && <span className="rsep" />}
        {ui.current.buttons.map((b) => <button key={b.label} type="button" className="rbtn" onClick={b.fn}><span>{b.label}</span></button>)}
      </div>

      {!isNew && <WorkflowBar doctype={doctype} name={name} onChanged={() => setReloadTick((n) => n + 1)} onGate={setWfGate} />}

      {!isNew && meta.is_submittable && docstatus === 2 && (
        <div className="banner cancelled" role="status">
          <b>This document is cancelled.</b> It stays on record but no longer counts.{" "}
          {amendedTo ? <>It was amended as <a href={`#/app/${encodeURIComponent(doctype)}/${encodeURIComponent(amendedTo)}`}>{amendedTo}</a>.</> : perms.create ? "To correct it, press Amend." : ""}
        </div>
      )}
      {!isNew && Boolean(doc.amended_from) && (
        <div className="banner amended" role="status">Amended from <a href={`#/app/${encodeURIComponent(doctype)}/${encodeURIComponent(String(doc.amended_from))}`}>{String(doc.amended_from)}</a> (cancelled).</div>
      )}
      {isNew && copied && (
        <div className="banner copied" role="status">
          {copied.mode === "amend" ? <>Amending <a href={`#/app/${encodeURIComponent(doctype)}/${encodeURIComponent(copied.source)}`}>{copied.source}</a>: change what was wrong, then Save{copied.suggested_name ? ` (it will be saved as ${copied.suggested_name})` : ""}.</>
            : <>Duplicated from <a href={`#/app/${encodeURIComponent(doctype)}/${encodeURIComponent(copied.source)}`}>{copied.source}</a>. Nothing is saved until you press Save.</>}
        </div>
      )}
      {ui.current.intro && <div className="intro">{ui.current.intro}</div>}
      {error && <div className="error" role="alert">{error}</div>}

      {meta.autoname === "prompt" && isNew && (
        <div className="field"><label htmlFor="f_name">Name *</label>
          <input id="f_name" type="text" value={doc.name ?? ""} onChange={(e) => frm.set_value("name", e.target.value)} /></div>
      )}

      {CustomForm ? <CustomForm doc={doc} meta={meta} frm={frm} readOnly={formReadOnly} isNew={isNew} onChange={(fieldname, value) => frm.set_value(fieldname, value)} /> : meta.layout ? (
        <GridForm layout={meta.layout} fields={fieldMap} hidden={{ ...conditionalState.hidden, ...ui.current.hidden }} tabIdx={tabIdx} onTab={setTabIdx} collapsed={collapsed}
          onToggle={(k) => setCollapsed((c) => ({ ...c, [k]: !c[k] }))}
          render={(f) => (
            <FieldControl key={f.fieldname} field={f} value={doc[f.fieldname]} childMetas={childMetas} invalid={invalid.includes(f.fieldname)}
              required={conditionalState.required[f.fieldname]} readOnly={formReadOnly || conditionalState.readOnly[f.fieldname] || ui.current.readOnly[f.fieldname]}
              appearance={meta.form_appearance?.[f.fieldname]} onChange={(v) => frm.set_value(f.fieldname, v)}
              onChildChange={(row, rowIndex, childField) => trigger(String(f.options), childField, frm, false, row, rowIndex)} />
          )} />
      ) : (
        <>
      {layout.length > 1 && (
        <nav className="tabs" role="tablist">
          {layout.map((t, i) => (
            <button key={t.label + i} role="tab" aria-selected={i === tabIdx} className={i === tabIdx ? "active" : ""}
              type="button" onClick={() => setTabIdx(i)}>{t.label}</button>
          ))}
        </nav>
      )}

      {layout.map((tab, ti) => (
        <div key={tab.label + ti} className="tab-panel" hidden={ti !== tabIdx} role="tabpanel">
          {tab.sections.map((sec, si) => (
            <section key={si} className={`section${collapsed[`${ti}:${si}`] ? " collapsed" : ""}`}>
              {sec.label && (
                <button type="button" className="section-head" aria-expanded={!collapsed[`${ti}:${si}`]}
                  onClick={() => setCollapsed((c) => ({ ...c, [`${ti}:${si}`]: !c[`${ti}:${si}`] }))}>
                  <span>{sec.label}</span><Icon name={collapsed[`${ti}:${si}`] ? "down" : "up"} />
                </button>
              )}
              {!collapsed[`${ti}:${si}`] && (
                <div className="business-form-grid">
                  {sec.columns.flatMap((col) => col.fields).filter((f) => !(conditionalState.hidden[f.fieldname] || ui.current.hidden[f.fieldname])).map((f) => (
                    <div key={f.fieldname} className={`business-form-cell span-${fieldGridSpan(f)}`} style={{ gridColumn: `span ${fieldGridSpan(f)}` }}>
                      <FieldControl field={f} value={doc[f.fieldname]} childMetas={childMetas}
                        invalid={invalid.includes(f.fieldname)} required={conditionalState.required[f.fieldname]}
                        readOnly={formReadOnly || conditionalState.readOnly[f.fieldname] || ui.current.readOnly[f.fieldname]}
                        appearance={meta.form_appearance?.[f.fieldname]}
                        onChange={(v) => frm.set_value(f.fieldname, v)}
                        onChildChange={(row, rowIndex, childField) => trigger(String(f.options), childField, frm, false, row, rowIndex)} />
                    </div>
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      ))}
        </>
      )}
      {!isNew && <AttachmentPanel doctype={doctype} name={name} canWrite={Boolean(perms.write)} />}
      {!isNew && <DocumentTimeline doctype={doctype} name={name} defaultCollapsed={!meta.is_submittable} />}
    </div>
  );
}

export { velora };
