import { useCallback, useEffect, useState } from "react";
import { api, consoleLock, errorMessage } from "../api";
import DatabaseTools from "./DatabaseTools";
import FileExplorer from "./FileExplorer";

type Tab = "files" | "database";

/** Files, database and SQL for platform administrators. Changing code or data needs the password again (the "unlock"), which lasts ten minutes. */
export default function ServerConsole({ initialPath = "", initialTab = "files" }: { initialPath?: string; initialTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [left, setLeft] = useState(consoleLock.left());
  const [asking, setAsking] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [resume, setResume] = useState<(() => void) | null>(null);

  useEffect(() => {
    const t = setInterval(() => setLeft(consoleLock.left()), 1000);
    return () => clearInterval(t);
  }, []);

  /** Pages call this before a change; it resolves when the console is unlocked (asking for the password if needed). */
  const needUnlock = useCallback((then?: () => void) => {
    if (consoleLock.left() > 0) { then?.(); return true; }
    setResume(() => then ?? null); setAsking(true);
    return false;
  }, []);

  async function unlock() {
    setBusy(true); setError("");
    try {
      const r = await api.consoleUnlock(password, code);
      consoleLock.set(r.token, r.expires_in); setLeft(consoleLock.left());
      setPassword(""); setCode(""); setAsking(false);
      const next = resume; setResume(null); next?.();
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  const mm = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  return (
    <div className="panel server-console">
      <div className="page-head"><div className="titles"><h1>Server Console</h1><span className="muted">Files, database and SQL for this server. Changes are logged and need your password.</span></div></div>
      <div className={`console-lock ${left ? "open" : ""}`} role="status">
        {left
          ? <><strong>Unlocked</strong> <span className="muted">{mm} left</span> <button className="rbtn" onClick={() => { consoleLock.clear(); setLeft(0); }}>Lock now</button></>
          : <><strong>Locked</strong> <span className="muted">Reading is free. Editing framework code or changing data asks for your password.</span> <button className="rbtn primary" onClick={() => needUnlock()}>Unlock</button></>}
      </div>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "files"} className={`rbtn ${tab === "files" ? "primary" : ""}`} onClick={() => setTab("files")}>Files</button>
        <button role="tab" aria-selected={tab === "database"} className={`rbtn ${tab === "database" ? "primary" : ""}`} onClick={() => setTab("database")}>Database and SQL</button>
      </div>
      {asking && (
        <section className="admin-card" role="dialog" aria-label="Unlock the Server Console">
          <h2>Unlock the Server Console</h2>
          <p className="muted">Enter your password again. The unlock lasts ten minutes and only works in this browser session.</p>
          {error && <div className="error" role="alert">{error}</div>}
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && password) void unlock(); }} autoFocus /></label>
          <label>Authenticator code (only if you use one)<input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} /></label>
          <div className="fe-tools">
            <button className="rbtn primary" disabled={busy || !password} onClick={() => void unlock()}>Unlock</button>
            <button className="rbtn" onClick={() => { setAsking(false); setError(""); setPassword(""); }}>Cancel</button>
          </div>
        </section>
      )}
      {tab === "files" ? <FileExplorer embedded initialPath={initialPath} unlocked={left > 0} needUnlock={needUnlock} /> : <DatabaseTools unlocked={left > 0} needUnlock={needUnlock} />}
    </div>
  );
}
