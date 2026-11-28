import { useState } from "react";
import { api, errorMessage } from "../api";
import Dialog from "../ui/Dialog";

/** Split what the user typed into addresses: commas or semicolons separate them, duplicates are dropped. */
export function parseRecipients(text: string): string[] {
  return [...new Set(text.split(/[,;]+/).map((x) => x.trim()).filter(Boolean))];
}
const looksLikeEmail = (x: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(x);

/** Email a document to one or many people (comma-separated) with a note in the message. */
export default function EmailDialog({ doctype, name, onClose }: { doctype: string; name: string; onClose: () => void }) {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState(`${doctype}: ${name}`);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{ recipients: string[]; failed: { recipient: string; error: string }[] } | null>(null);
  const list = parseRecipients(to);
  const invalid = list.filter((x) => !looksLikeEmail(x));

  async function send() {
    setError("");
    if (!list.length) return setError("Enter at least one email address.");
    if (invalid.length) return setError(`Not a valid email address: ${invalid.join(", ")}`);
    setBusy(true);
    try {
      const r = await api.emailDocument(doctype, name, { recipients: list, subject, message });
      setResult({ recipients: r.recipients ?? [r.recipient], failed: r.failed ?? [] });
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  return (
    <Dialog title={`Email ${doctype} ${name}`} onClose={onClose} footer={result
      ? <button type="button" className="btn primary" onClick={onClose}>Close</button>
      : <><button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn primary" disabled={busy} onClick={() => void send()}>{busy ? "Sending…" : `Send${list.length > 1 ? ` to ${list.length}` : ""}`}</button></>}>
      {error && <div className="error" role="alert">{error}</div>}
      {result ? (
        <div>
          <p>Sent to {result.recipients.length} recipient{result.recipients.length === 1 ? "" : "s"}: {result.recipients.join(", ")}.</p>
          {result.failed.length > 0 && <div className="error" role="alert">Not sent: {result.failed.map((f) => `${f.recipient} (${f.error})`).join("; ")}</div>}
        </div>
      ) : (
        <div className="stack">
          <div className="field"><label htmlFor="email-to">To</label>
            <input id="email-to" type="text" autoFocus value={to} placeholder="name@company.com, other@company.com" onChange={(e) => setTo(e.target.value)} />
            <small>Separate several addresses with commas.{list.length > 1 ? ` ${list.length} recipients.` : ""}</small></div>
          <div className="field"><label htmlFor="email-subject">Subject</label>
            <input id="email-subject" type="text" maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} /></div>
          <div className="field"><label htmlFor="email-note">Message</label>
            <textarea id="email-note" rows={6} value={message} placeholder="Add a note for the recipients (optional)" onChange={(e) => setMessage(e.target.value)} /></div>
        </div>
      )}
    </Dialog>
  );
}
