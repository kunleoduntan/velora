import { useEffect, useState } from "react";
import { auth, errorMessage } from "../api";

/** Live feedback that mirrors the server rules (the server still decides). */
export function strength(pw: string, email = ""): { score: number; label: string; ok: boolean } {
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
  const mixed = /[A-Za-z]/.test(pw) && /[^A-Za-z]/.test(pw);
  const name = email.split("@")[0].toLowerCase();
  const long = pw.length >= 16;
  const ok = pw.length >= 10 && (long || (classes >= 2 && mixed)) && !(name.length >= 4 && pw.toLowerCase().includes(name));
  const score = Math.min(4, (pw.length >= 10 ? 1 : 0) + (classes >= 3 ? 1 : 0) + (long ? 1 : 0) + (ok ? 1 : 0));
  return { score, ok, label: ["Too short", "Weak", "Fair", "Good", "Strong"][ok ? Math.max(score, 2) : Math.min(score, 1)] };
}

export function Meter({ password, email }: { password: string; email?: string }) {
  if (!password) return <p className="pw-rules">At least 10 characters with letters and numbers, or a passphrase of 16 or more.</p>;
  const s = strength(password, email);
  return <div className="pw-meter" role="status" aria-live="polite"><span className={`pw-bar pw-${s.ok ? s.score : 1}`}><i style={{ width: `${(s.ok ? Math.max(s.score, 2) : 1) * 25}%` }} /></span><small>{s.label}</small></div>;
}

/** "Forgot password?": says what will happen, never whether the account exists. */
export function ForgotPassword({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<"email" | "administrator" | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { setDone((await auth.forgotPassword(email.trim())).mode); } catch (x) { setError(errorMessage(x)); } finally { setBusy(false); }
  }
  if (done) return (
    <div className="login-form pw-done" role="status">
      <h3>{done === "email" ? "Check your email" : "Request sent to your administrator"}</h3>
      <p>{done === "email" ? "If that address belongs to an active account, a reset link is on its way. It works once and expires in 30 minutes."
        : "Email is not set up here, so your administrator has been asked to give you a temporary password. You will choose your own at your first sign-in."}</p>
      <button type="button" className="login-submit" onClick={onBack}>Back to sign in</button>
    </div>);
  return (
    <form className="login-form" onSubmit={submit}>
      {error && <div className="error" role="alert">{error}</div>}
      <label htmlFor="forgot-email">Email address</label>
      <input id="forgot-email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" required autoFocus />
      <button className="login-submit" type="submit" disabled={busy || !email}>{busy ? "Sending…" : "Reset my password"}</button>
      <button type="button" className="pw-link" onClick={onBack}>← Back to sign in</button>
    </form>);
}

/** Opened from the emailed link: #/reset-password?token=... */
export function ResetWithToken({ token, onDone }: { token: string; onDone: () => void }) {
  const [pw, setPw] = useState(""); const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [ok, setOk] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pw !== again) { setError("The two passwords do not match."); return; }
    setBusy(true); setError("");
    try { await auth.resetPassword(token, pw); setOk(true); } catch (x) { setError(errorMessage(x)); } finally { setBusy(false); }
  }
  if (ok) return <div className="login-form pw-done" role="status"><h3>Password changed</h3><p>You can sign in with your new password now.</p><button className="login-submit" onClick={onDone}>Go to sign in</button></div>;
  return (
    <form className="login-form" onSubmit={submit}>
      {error && <div className="error" role="alert">{error}</div>}
      <label htmlFor="reset-new">New password</label>
      <input id="reset-new" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required autoFocus />
      <Meter password={pw} />
      <label htmlFor="reset-again">Repeat new password</label>
      <input id="reset-again" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
      <button className="login-submit" type="submit" disabled={busy || !strength(pw).ok || !again}>{busy ? "Saving…" : "Save new password"}</button>
    </form>);
}

/** Shown instead of the app when the session uses a temporary password. */
export function ChangePasswordRequired({ email, onDone }: { email: string; onDone: () => void }) {
  const [cur, setCur] = useState(""); const [pw, setPw] = useState(""); const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pw !== again) { setError("The two new passwords do not match."); return; }
    setBusy(true); setError("");
    try { await auth.changePassword(cur, pw); onDone(); } catch (x) { setError(errorMessage(x)); setBusy(false); }
  }
  return (
    <main className="login-screen"><div className="login-layout"><section className="login-main-panel"><div className="login-card">
      <span className="login-eyebrow login-eyebrow-light">ONE MORE STEP</span>
      <h2>Choose your own password</h2>
      <p className="login-description">You signed in with a temporary password. Choose a new one that only you know; then sign in again.</p>
      <form className="login-form" onSubmit={submit}>
        {error && <div className="error" role="alert">{error}</div>}
        <label htmlFor="chg-cur">Temporary password</label>
        <input id="chg-cur" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required autoFocus />
        <label htmlFor="chg-new">New password</label>
        <input id="chg-new" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required />
        <Meter password={pw} email={email} />
        <label htmlFor="chg-again">Repeat new password</label>
        <input id="chg-again" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />
        <button className="login-submit" type="submit" disabled={busy || !cur || !strength(pw, email).ok || !again}>{busy ? "Saving…" : "Save and sign in again"}</button>
      </form>
    </div></section></div></main>);
}

export function resetTokenFromHash(): string | null {
  const m = /^#\/reset-password\?token=([\w-]+)$/.exec(window.location.hash);
  return m ? m[1] : null;
}

export function useResetToken(): [string | null, () => void] {
  const [token, setToken] = useState<string | null>(resetTokenFromHash());
  useEffect(() => { const on = () => setToken(resetTokenFromHash()); window.addEventListener("hashchange", on); return () => window.removeEventListener("hashchange", on); }, []);
  return [token, () => { window.location.hash = ""; setToken(null); }];
}
