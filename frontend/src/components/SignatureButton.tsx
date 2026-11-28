import { useState } from "react";
import { api, errorMessage } from "../api";
import Button from "../ui/Button";
import Dialog from "../ui/Dialog";

/** "My Signature": a short signature added, with the time, to documents this user approves (when signing is switched on). */
export default function SignatureButton() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  async function show() {
    setOpen(true); setMsg("");
    try { const r = await api.mySignature(); setValue(r.signature ?? ""); } catch (e) { setMsg(errorMessage(e)); }
  }
  async function save() {
    setBusy(true); setMsg("");
    try { await api.saveMySignature(value); setOpen(false); } catch (e) { setMsg(errorMessage(e)); } finally { setBusy(false); }
  }
  return (<>
    <button className="link" type="button" onClick={show}>My Signature</button>
    {open && <Dialog title="My Signature" onClose={() => setOpen(false)}
      footer={<><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" disabled={busy || !value.trim()} onClick={save}>Save</Button></>}>
      <p className="muted">A short signature (up to 40 characters), such as your initials or name. When signing is switched on, it is added with the date and time to documents you approve.</p>
      <div className="field"><label htmlFor="my-signature">Signature</label><input id="my-signature" maxLength={40} value={value} onChange={(e) => setValue(e.target.value)} /></div>
      {msg && <div className="error" role="alert">{msg}</div>}
    </Dialog>}
  </>);
}
