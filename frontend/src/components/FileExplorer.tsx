import { useCallback, useEffect, useRef, useState } from "react";
import { api, downloadBlob, errorMessage, type FmEntry, type FmFile } from "../api";

const join = (a: string, b: string) => (a ? `${a}/${b}` : b);
const parent = (p: string) => p.split("/").slice(0, -1).join("/");
function size(n: number | null) {
  if (n === null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

/** A small file explorer for the server's Velora folders (apps, files, backups, logs). Every rule is enforced on the server. */
export default function FileExplorer({ initialPath = "" }: { initialPath?: string }) {
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<FmEntry[]>([]);
  const [canWrite, setCanWrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState<FmFile | null>(null);
  const [text, setText] = useState("");
  const [deleting, setDeleting] = useState<FmEntry | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async (p: string) => {
    setError("");
    try {
      const r = await api.fmList(p);
      setPath(r.path); setEntries(r.entries); setCanWrite(r.can_write);
    } catch (e) { setError(errorMessage(e)); }
  }, []);
  useEffect(() => { void load(initialPath); }, [load, initialPath]);

  async function act(fn: () => Promise<unknown>, done?: string) {
    setBusy(true); setError(""); setMessage("");
    try { await fn(); if (done) setMessage(done); await load(path); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  async function upload(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    setBusy(true); setError(""); setMessage("");
    let ok = 0;
    try {
      for (const f of list) {
        try { await api.fmUpload(path, f); ok++; }
        catch (e) {
          const msg = errorMessage(e);
          if (/already exists/i.test(msg) && window.confirm(`${f.name} already exists here. Replace it?`)) { await api.fmUpload(path, f, true); ok++; }
          else throw e;
        }
      }
      setMessage(`Uploaded ${ok} file${ok === 1 ? "" : "s"}.`);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); await load(path); }
  }

  async function open(e: FmEntry) {
    const p = join(path, e.name);
    if (e.type === "dir") return load(p);
    if (e.type === "link") return;
    if (!e.editable) { void download(e); return; }
    try { const f = await api.fmRead(p); setEditing(f); setText(f.content); }
    catch (er) { setError(errorMessage(er)); }
  }

  async function download(e: FmEntry) {
    try {
      const res = await fetch(api.fmDownloadUrl(join(path, e.name)), { credentials: "same-origin", headers: { "X-Velora-Request": "1" } });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).message ?? res.statusText);
      downloadBlob(await res.blob(), e.name);
    } catch (er) { setError(errorMessage(er)); }
  }

  async function save() {
    if (!editing) return;
    setBusy(true); setError("");
    try {
      await api.fmWrite(editing.path, text, editing.modified);
      setEditing(null); setMessage("Saved."); await load(path);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  const crumbs = path ? path.split("/") : [];
  return (
    <div className="panel file-explorer"
      onDragOver={e => { if (canWrite) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={() => setDragging(false)}
      onDrop={e => { e.preventDefault(); setDragging(false); if (canWrite) void upload(e.dataTransfer.files); }}
      onPaste={e => { if (canWrite && e.clipboardData.files.length) void upload(e.clipboardData.files); }}>
      <div className="page-head"><div className="titles"><h1>File Explorer</h1><span className="muted">Browse, upload, edit and download files on this server</span></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      {message && <div className="success" role="status">{message}</div>}
      <nav className="fe-crumbs" aria-label="Folder path">
        <button className="rbtn" onClick={() => load("")}>Home</button>
        {crumbs.map((c, i) => <button key={i} className="rbtn" onClick={() => load(crumbs.slice(0, i + 1).join("/"))}>{c}</button>)}
        {path && <button className="rbtn" onClick={() => load(parent(path))}>Up</button>}
      </nav>
      {canWrite
        ? <div className="fe-tools">
            <input ref={input} type="file" multiple hidden aria-label="Choose files to upload" onChange={e => { if (e.target.files) void upload(e.target.files); e.target.value = ""; }} />
            <button className="rbtn primary" disabled={busy} onClick={() => input.current?.click()}>Upload files</button>
            <button className="rbtn" disabled={busy} onClick={() => { const n = window.prompt("New folder name"); if (n) void act(() => api.fmMkdir(join(path, n)), "Folder created."); }}>New folder</button>
            <button className="rbtn" disabled={busy} onClick={() => { const n = window.prompt("New file name"); if (n) void act(() => api.fmNewFile(join(path, n)), "File created."); }}>New file</button>
            <span className="muted">Drag files here, or paste them, to upload.</span>
          </div>
        : <p className="muted">{path ? "This folder is read-only here." : "Pick a folder to begin."}</p>}
      {dragging && <div className="fe-drop" role="status">Drop to upload to /{path}</div>}
      <div className="fe-list" role="table" aria-label="Files">
        {entries.length === 0 && <p className="muted">This folder is empty.</p>}
        {entries.map(e => (
          <div className="fe-row" role="row" key={e.name}>
            <button className="fe-name" role="cell" onClick={() => void open(e)} aria-label={`${e.type === "dir" ? "Open folder" : "Open"} ${e.name}`}>
              <span aria-hidden="true">{e.type === "dir" ? "📁" : e.type === "link" ? "🔗" : "📄"}</span> {e.name}
            </button>
            <span className="muted fe-meta" role="cell">{size(e.size)}</span>
            <span className="muted fe-meta" role="cell">{e.modified?.replace("T", " ").replace(/\+00:00$/, " UTC") ?? ""}</span>
            <span className="fe-actions" role="cell">
              {e.type === "file" && <button className="rbtn" onClick={() => void download(e)} aria-label={`Download ${e.name}`}>Download</button>}
              {path && canWrite && e.type !== "link" && <button className="rbtn" onClick={() => { const n = window.prompt("Rename to", e.name); if (n && n !== e.name) void act(() => api.fmRename(join(path, e.name), n), "Renamed."); }} aria-label={`Rename ${e.name}`}>Rename</button>}
              {path && e.can_delete && <button className="rbtn danger" onClick={() => setDeleting(e)} aria-label={`Delete ${e.name}`}>Delete</button>}
            </span>
          </div>
        ))}
      </div>

      {editing && (
        <section className="admin-card fe-editor" role="dialog" aria-label={`Edit ${editing.path}`}>
          <h2>{editing.path}</h2>
          <textarea rows={22} value={text} onChange={e => setText(e.target.value)} spellCheck={false} aria-label="File contents" style={{ width: "100%", fontFamily: "monospace" }} />
          <div className="fe-tools">
            <button className="rbtn primary" disabled={busy || text === editing.content} onClick={() => void save()}>Save</button>
            <button className="rbtn" onClick={() => setEditing(null)}>Close</button>
          </div>
        </section>
      )}

      {deleting && (
        <section className="admin-card" role="dialog" aria-label="Delete file">
          <h2>Delete {deleting.name}?</h2>
          <p className="muted">{deleting.type === "dir" ? "This removes the folder and everything inside it." : "This removes the file."} It cannot be undone.</p>
          <div className="fe-tools">
            <button className="rbtn danger" disabled={busy} onClick={() => { const d = deleting; setDeleting(null); void act(() => api.fmDelete(join(path, d.name), d.type === "dir"), "Deleted."); }}>Delete permanently</button>
            <button className="rbtn" onClick={() => setDeleting(null)}>Cancel</button>
          </div>
        </section>
      )}
    </div>
  );
}
