import { useEffect, useState } from "react";
import { api, errorMessage, type LifecycleEvent, type WelcomeData } from "../api";
import { ago } from "./NotificationBell";

export const SEEN_KEY = "velora.welcome.seen";
const read = () => { try { return localStorage.getItem(SEEN_KEY); } catch { return null; } };
const write = (v: string) => { try { localStorage.setItem(SEEN_KEY, v); } catch { /* private mode: the page just shows again */ } };

/** After the first sign-in following an install, update or upgrade, open the welcome page ONCE. Renders nothing. */
export function WelcomeGate() {
  useEffect(() => {
    let live = true;
    api.welcome().then((w) => {
      const home = !window.location.hash || window.location.hash === "#" || window.location.hash === "#/";
      if (live && w.latest && w.latest.id !== read() && home) window.location.hash = "#/welcome";
    }).catch(() => { /* not available here: stay on the home screen */ });
    return () => { live = false; };
  }, []);
  return null;
}

export const KIND_LABEL: Record<string, string> = { install: "Installed", update: "Updated", upgrade: "Upgraded", "install-app": "App added", "uninstall-app": "App removed", domain: "Address" };

function Steps({ ev }: { ev: LifecycleEvent }) {
  return (
    <ul className="wl-steps">
      {ev.steps.map((s, i) => <li key={i} className={s.ok ? "ok" : "bad"}><span aria-hidden="true">{s.ok ? "✓" : "✗"}</span><span className="sr-only">{s.ok ? "Done: " : "Problem: "}</span>{s.text}</li>)}
      {ev.steps.length === 0 && <li className="muted">No details were recorded for this one.</li>}
    </ul>
  );
}

function Explain({ title, children }: { title: string; children: React.ReactNode }) {
  return <details className="wl-explain"><summary>{title}</summary><div>{children}</div></details>;
}

export default function WelcomePage() {
  const [w, setW] = useState<WelcomeData | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => { api.welcome().then(setW).catch((e) => setError(errorMessage(e))); }, []);

  if (error) return <div className="error" role="alert">{error}</div>;
  if (!w) return <div className="panel muted">Loading your welcome page…</div>;

  const done = () => { if (w.latest) write(w.latest.id); window.location.hash = "#/"; };
  const copy = async (text: string) => { try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* the command is visible: select and copy */ } };
  const cmd = "sudo velora domain add erp.yourcompany.com";
  const latest = w.latest;
  const headline = !latest ? "Welcome to Velora" : latest.kind === "install" ? "Your system is ready" : latest.ok ? `${latest.title}` : "Something needs your attention";
  const sub = !latest ? "Here is a quick guide to what you have." : latest.kind === "install" ? "Velora is installed. Here is exactly what was set up for you." : "Here is exactly what just happened.";

  return (
    <div className="welcome">
      <header className="wl-hero">
        <div className="wl-logo" aria-hidden="true"><svg viewBox="0 0 40 40"><defs><linearGradient id="wlg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#fff" stopOpacity=".95" /><stop offset="1" stopColor="#d7f7f1" /></linearGradient></defs><rect width="40" height="40" rx="11" fill="rgba(255,255,255,.2)" /><path d="M9 12l11 18 11-18" fill="none" stroke="url(#wlg)" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" /></svg></div>
        <h1>{headline}</h1>
        <p>{sub}</p>
        {latest?.from_version && latest.to_version && <p className="wl-versions"><span>{latest.from_version}</span> <b aria-label="to">→</b> <span>{latest.to_version}</span></p>}
        <div className="wl-actions">
          <button type="button" className="wl-btn primary" onClick={() => window.open(w.tutorial_url, "_blank", "noopener")}>Open the full tutorial ↗</button>
          <button type="button" className="wl-btn" onClick={done}>{latest ? "Got it, take me to my work" : "Take me to my work"}</button>
        </div>
      </header>

      <div className="wl-grid">
        <section className="wl-card" aria-label="What just happened">
          <h2>What just happened</h2>
          {latest ? (
            <>
              <p className={latest.ok ? "wl-ok" : "wl-bad"}><b>{latest.title}</b> <span className="muted">· {ago(latest.at)}</span></p>
              <Steps ev={latest} />
            </>
          ) : <p className="muted">Nothing has been recorded yet. After an install, update or upgrade, the steps taken appear here.</p>}
        </section>

        <section className="wl-card" aria-label="Your system">
          <h2>Your system</h2>
          <dl className="wl-facts">
            <dt>Velora</dt><dd>version {w.version}</dd>
            {w.company && <><dt>Company</dt><dd>{w.company.name} <span className="muted">({w.company.id})</span></dd></>}
            <dt>Signed in as</dt><dd>{w.user}{w.is_admin ? " · administrator" : ""}</dd>
          </dl>
          <h3>Apps in this company</h3>
          <div className="wl-chips">{w.apps.map((a) => <span key={a.name} className={`wl-chip${a.built_in ? " built" : ""}`} title={a.description}>{a.title}{a.built_in ? " · built in" : ""}{a.guide_url && <> · <a href={a.guide_url} target="_blank" rel="noopener">How-to ↗</a></>}</span>)}{w.apps.length === 0 && <span className="muted">None yet.</span>}</div>
        </section>
      </div>

      <section className="wl-card" aria-label="Start here">
        <h2>Start here</h2>
        <ol className="wl-quick">
          <li><b>Create your first record type.</b> {w.is_admin ? <a href="#/settings/doctype-creator">Open the DocType Creator</a> : <span className="muted">Ask an administrator to open the DocType Creator.</span>} or run <code>velora new-doctype "Name" --app myapp</code>.</li>
          <li><b>Arrange any form your way.</b> Open a form and press <b>Customize form</b>: drag, resize, add sections and tabs.</li>
          <li><b>Be told when things happen.</b> {w.features.notifications ? (w.is_admin ? <a href="#/app/Notification Rule">Create a notification rule</a> : "Notifications are on.") : <span className="muted">Notifications are not installed here (<code>velora install-app velora_notify</code>).</span>}</li>
          <li><b>Find anything.</b> {w.features.search ? <>Press <kbd>Ctrl</kbd>+<kbd>K</kbd> and type part of a name.</> : <span className="muted">Search is not installed here (<code>velora install-app velora_search</code>).</span>}</li>
          <li><b>Give this company its own web address.</b> {w.domains.length ? <>Already set: {w.domains.map((d) => <code key={d.domain}>{d.domain}</code>)}.</> : "One command on your server:"}
            <div className="wl-cmd"><code>{cmd}</code><button type="button" className="wl-btn small" onClick={() => copy(cmd)}>{copied ? "Copied" : "Copy"}</button></div></li>
        </ol>
      </section>

      <section className="wl-card" aria-label="How Velora works">
        <h2>How Velora works</h2>
        <Explain title="Velora is a framework, not an ERP"><p>Velora provides documents, forms, permissions, reports, notifications, search and the installer. Your business rules live in separate <b>apps</b>, so the core never fills up with industry-specific code and each app can be installed, updated and removed on its own.</p></Explain>
        <Explain title="Every company has its own database"><p>Customers, suppliers, accounts and transactions are never shared between companies, even in the same group. A failed upgrade, a restore or a slow report in one company cannot touch another. One login can reach several companies, with a different role in each.</p></Explain>
        <Explain title="Updating is safe"><p><code>sudo velora update</code> fetches new code and packages, takes a backup, upgrades every company, and restarts. If anything fails, the code and every database are put back exactly as they were, and this page tells you what happened.</p></Explain>
        <Explain title="Notifications and search"><p>Rules tell the right people when something happens (in-app, email, webhook), with quiet hours and digests. Search finds any record you may read, ignoring accents and forgiving small typos.</p></Explain>
        <Explain title="Built for PostgreSQL"><p>On PostgreSQL the database itself protects the ledger (entries can never be edited or deleted, vouchers must balance), notifications arrive instantly, and <code>velora pg status</code> advises on backups and tuning.</p></Explain>
      </section>

      <section className="wl-card" aria-label="What's new">
        <h2>What's new</h2>
        {w.events.length === 0 && <p className="muted">The history of installs, updates and changes will appear here.</p>}
        <ol className="wl-timeline">
          {w.events.map((e) => (
            <li key={e.id} className={e.ok ? "" : "bad"}>
              <details><summary><span className="wl-kind">{KIND_LABEL[e.kind] ?? e.kind}</span> {e.title} <span className="muted">· {ago(e.at)}</span></summary><Steps ev={e} /></details>
            </li>
          ))}
        </ol>
      </section>

      <footer className="wl-foot">Powered by <b>{w.powered_by}</b></footer>
    </div>
  );
}
