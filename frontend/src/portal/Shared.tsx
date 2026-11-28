import { useState } from "react";
import { day, portal } from "./portalApi";
import type { Preferences } from "./portalApi";
import { Message, Retry, Skeleton, Switch } from "./ui";
import { useResource } from "./useResource";

const EMBLEM: Record<string, string> = { Birthday: "🎂", "Work Anniversary": "🏆", "Partnership Anniversary": "🤝", Holiday: "🎉", "Win Back": "👋", Custom: "✨" };

/** The kind words the company has sent this person, newest first. */
export function Messages() {
  const r = useResource(() => portal.messages(), []);
  return <><h1>Messages from us</h1><p className="pt-muted">Greetings and notes the company has sent you.</p>
    {r.error && <Retry error={r.error} onRetry={r.reload} />}
    {r.loading && <Skeleton rows={4} />}
    {r.data && !r.data.length && <div className="pt-card pt-empty"><span aria-hidden="true">💌</span><p>Nothing yet. Birthday wishes, festive greetings and updates will appear here.</p></div>}
    {r.data?.map(m => <article className="pt-card pt-note" key={m.name}><span className="pt-emblem" aria-hidden="true">{EMBLEM[m.kind] ?? "✨"}</span>
      <div><h2>{m.subject}</h2><small className="pt-muted">{day(m.moment_date)}</small><p>{m.message.split(/\n\s*\n/)[0]}</p></div></article>)}</>;
}

/** One switch: whether the company may email greetings and updates. Staff-sent invoices and statements are not affected. */
export function PreferencesCard() {
  const r = useResource<Preferences>(() => portal.preferences(), []);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [saved, setSaved] = useState<Preferences | null>(null);
  const prefs = saved ?? r.data;
  async function set(v: boolean) { setBusy(true); setError(""); try { setSaved(await portal.savePreferences(v)); } catch (e) { setError(e instanceof Error ? e.message : "Could not save."); } finally { setBusy(false); } }
  if (r.loading) return <Skeleton rows={2} />;
  if (r.error) return <Retry error={r.error} onRetry={r.reload} />;
  if (!prefs?.available) return null;
  return <section className="pt-card"><h2>Greetings and updates</h2>
    <div className="pt-pref"><div><strong>Send me greetings by email</strong><p className="pt-muted">Birthday wishes, festive greetings and friendly updates to {prefs.addresses.join(" and ")}.</p></div>
      <Switch checked={prefs.messages_enabled} disabled={busy} label="Send me greetings by email" onChange={v => void set(v)} /></div>
    {error && <Message kind="error">{error}</Message>}</section>;
}
