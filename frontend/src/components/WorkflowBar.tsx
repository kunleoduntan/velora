import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type Action = { action: string; label?: string; to_state: string; can_act: boolean; reason?: string; step?: string; step_label?: string };
type Flow = {
  workflow: string; state_field?: string; state?: string; status?: string; instance_id?: string | null;
  can_start?: boolean; actions: Action[]; history: { actor?: string; action: string; from_state?: string; to_state: string; comment?: string; created_on?: string }[];
  locked?: boolean; submit_ready?: boolean; submit_states?: string[];
};

/** The approval bar on a document: where it stands, what you may do next, and who did what. */
export default function WorkflowBar({ doctype, name, onChanged, onGate }: { doctype: string; name: string; onChanged: () => void; onGate?: (g: { waiting: boolean; locked: boolean }) => void }) {
  const [flow, setFlow] = useState<Flow | null>(null), [comment, setComment] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState(""), [showHistory, setShowHistory] = useState(false);
  useEffect(() => {
    let live = true;
    api.documentWorkflow(doctype, name).then((f) => { if (live) setFlow(f); }).catch(() => { if (live) setFlow(null); });
    return () => { live = false; };
  }, [doctype, name]);
  useEffect(() => {
    onGate?.(flow ? { waiting: !!flow.submit_states?.length && flow.submit_ready === false, locked: !!flow.locked } : { waiting: false, locked: false });
  }, [flow]);
  if (!flow) return null;
  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await fn(); setComment(""); setFlow(await api.documentWorkflow(doctype, name)); onChanged(); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  const mine = flow.actions.filter((a) => a.can_act), others = flow.actions.filter((a) => !a.can_act);
  const tone = /reject|cancel|return/i.test(flow.state || "") ? "danger" : /approv|complet|clos|clear/i.test(flow.state || "") ? "ok" : "pending";
  return (
    <section className={`wf-bar wf-${tone}`} aria-label="Approval">
      <div className="wf-head">
        <div><span className="wf-label">Approval · {flow.workflow}</span><b className="wf-state">{flow.state || "Not started"}</b></div>
        {flow.locked && <span className="wf-chip" title="This state locks the content; reopen it through the workflow to edit">Locked</span>}
        {flow.submit_ready === false && flow.submit_states?.length ? <span className="wf-chip warn" title="The document can only be submitted once it reaches one of these states">Submit after: {flow.submit_states.join(" / ")}</span> : null}
        {flow.submit_ready && <span className="wf-chip ok">Ready to submit</span>}
      </div>
      {flow.can_start && !flow.instance_id && <div className="wf-actions"><button type="button" className="rbtn primary" disabled={busy} onClick={() => run(() => api.startDocumentWorkflow(doctype, name))}>Start approval</button><span className="muted">This document has not entered its approval workflow yet.</span></div>}
      {mine.length > 0 && (
        <div className="wf-actions">
          <input aria-label="Comment" placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} />
          {mine.map((a) => <button key={a.action + (a.step || "")} type="button" className={`rbtn ${/reject|return|decline/i.test(a.action) ? "danger" : "primary"}`} disabled={busy}
            onClick={() => run(() => api.workflowAction(flow.instance_id as string, a.action, comment, a.step))} title={`Moves to ${a.to_state}`}>{a.label || a.action}{a.step_label ? ` · ${a.step_label}` : ""}</button>)}
        </div>
      )}
      {mine.length === 0 && others.length > 0 && flow.instance_id && <p className="muted wf-wait">Waiting for {Array.from(new Set(others.map((a) => a.reason || "an approver"))).join(" · ")}.</p>}
      {error && <div className="error" role="alert">{error}</div>}
      {flow.history.length > 0 && (
        <div className="wf-history">
          <button type="button" className="link-btn" aria-expanded={showHistory} onClick={() => setShowHistory((v) => !v)}>{showHistory ? "Hide" : "Show"} approval history ({flow.history.length})</button>
          {showHistory && <ol>{flow.history.map((h, i) => <li key={i}><b>{h.action}</b> · {h.from_state ? `${h.from_state} → ` : ""}{h.to_state} <span className="muted">by {h.actor || "system"}{h.created_on ? ` · ${String(h.created_on).replace("T", " ").slice(0, 16)}` : ""}</span>{h.comment ? <em> — {h.comment}</em> : null}</li>)}</ol>}
        </div>
      )}
    </section>
  );
}
