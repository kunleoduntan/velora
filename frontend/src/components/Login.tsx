import { useEffect, useState } from "react";
import { auth, errorMessage, setProfile, setSession, type AuthMode } from "../api";

type LoginBranding = { app_name: string; tagline: string; logo_url: string };
const DEFAULT_BRANDING: LoginBranding = {
  app_name: "Velora",
  tagline: "Enterprise operations, in control.",
  logo_url: "",
};

/** A branded, responsive sign-in experience. Company domains can supply their own logo and brand name. */
export default function Login({ mode, onDone }: { mode: AuthMode; onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [user, setUser] = useState("sam");
  const [roles, setRoles] = useState("Sales User");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [brand, setBrand] = useState<LoginBranding>(DEFAULT_BRANDING);
  const [logoFailed, setLogoFailed] = useState(false);

  useEffect(() => {
    if (mode !== "password") return;
    let current = true;
    auth.loginBranding().then((result) => {
      if (current) { setBrand({ ...DEFAULT_BRANDING, ...result }); setLogoFailed(false); }
    }).catch(() => { /* the default Velora identity keeps sign-in available */ });
    return () => { current = false; };
  }, [mode]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      setProfile(await auth.login(email, password, totp || undefined));
      setPassword(""); setTotp(""); onDone();
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  };

  return (
    <main className="login-screen">
      <div className="login-layout">
        <section className="login-brand-panel" aria-label={`${brand.app_name} branding`}>
          <div className="login-brand-top">
            {brand.logo_url && !logoFailed
              ? <img className="login-brand-logo" src={brand.logo_url} alt={`${brand.app_name} logo`} onError={() => setLogoFailed(true)} />
              : <span className="login-brand-mark" aria-hidden="true">V</span>}
            <span className="login-brand-name">{brand.app_name || "Velora"}</span>
          </div>
          <div className="login-brand-message">
            <span className="login-eyebrow">BUSINESS MANAGEMENT PLATFORM</span>
            <h1>Bring your business into focus.</h1>
            <p>{brand.tagline || DEFAULT_BRANDING.tagline}</p>
          </div>
          <div className="login-brand-footer">
            <span className="login-orbit login-orbit-one" />
            <span className="login-orbit login-orbit-two" />
            <span className="login-secure"><span aria-hidden="true">◆</span> Secure enterprise workspace</span>
            <span className="login-version">VELORA ERP</span>
          </div>
        </section>

        <section className="login-main-panel">
          <div className="login-card">
            <div className="login-mobile-brand">
              {brand.logo_url && !logoFailed
                ? <img className="login-brand-logo" src={brand.logo_url} alt={`${brand.app_name} logo`} onError={() => setLogoFailed(true)} />
                : <span className="login-brand-mark" aria-hidden="true">V</span>}
              <strong>{brand.app_name || "Velora"}</strong>
            </div>
            <span className="login-eyebrow login-eyebrow-light">WELCOME</span>
            <h2>{mode === "password" ? "Sign in to your workspace" : "Developer sign-in"}</h2>
            <p className="login-description">{mode === "password"
              ? "Use your account credentials to securely access your business workspace."
              : "Local development access. Backend permissions remain enforced for the roles you choose."}</p>
            {error && <div className="error" role="alert">{error}</div>}

            {mode === "password" ? (
              <form className="login-form" onSubmit={submit}>
                <label htmlFor="login-email">Email address</label>
                <input id="login-email" type="email" autoComplete="username" value={email}
                  onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" required />
                <label htmlFor="login-password">Password</label>
                <input id="login-password" type="password" autoComplete="current-password" value={password}
                  onChange={(e) => setPassword(e.target.value)} placeholder="Enter your password" required />
                <label htmlFor="login-totp">Authenticator code <span>(optional)</span></label>
                <input id="login-totp" inputMode="numeric" autoComplete="one-time-code" value={totp}
                  onChange={(e) => setTotp(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="6-digit code" />
                <button className="login-submit" type="submit" disabled={busy || !email || !password}>
                  {busy ? <><span className="login-spinner" /> Signing in…</> : <>Sign in <span aria-hidden="true">→</span></>}
                </button>
              </form>
            ) : (
              <div className="login-form">
                <label htmlFor="login-user">User</label>
                <input id="login-user" value={user} onChange={(e) => setUser(e.target.value)} />
                <label htmlFor="login-roles">Roles <span>(comma separated)</span></label>
                <input id="login-roles" value={roles} onChange={(e) => setRoles(e.target.value)} />
                <div className="login-presets">
                  <button type="button" onClick={() => { setUser("sam"); setRoles("Sales User"); }}>Sales User</button>
                  <button type="button" onClick={() => { setUser("admin"); setRoles("System Manager"); }}>System Manager</button>
                </div>
                <button className="login-submit" type="button" onClick={() => { setSession({ user, roles }); onDone(); }}>
                  Sign in <span aria-hidden="true">→</span>
                </button>
              </div>
            )}
            <p className="login-help">Your workspace is protected. Contact your system administrator if you need access.</p>
          </div>
          <footer className="login-main-footer"><span>© {new Date().getFullYear()} {brand.app_name || "Velora"}</span><span>Enterprise resource planning</span></footer>
        </section>
      </div>
    </main>
  );
}
