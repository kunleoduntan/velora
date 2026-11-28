import { useEffect, useState } from "react";
import { api, errorMessage, type NotificationItem, type NotificationPrefs } from "../api";
import { ago, target } from "./NotificationBell";

const DIGESTS = ["Immediately", "Hourly digest", "Daily digest"];
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Your notifications (all or unread) and how you want to receive them. */
export default function NotificationsPage() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [unreadCount, setUnreadCount] = useState(0);
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  async function load(reset = true, unread = onlyUnread) {
    try {
      const r = await api.notifications({ unread, limit: 20, offset: reset ? 0 : items.length });
      setItems((cur) => (reset ? r.items : [...cur, ...r.items])); setTotal(unread ? r.unread : r.total); setUnreadCount(r.unread);
    } catch (e) { setError(errorMessage(e)); }
  }
  useEffect(() => { void load(true, onlyUnread); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [onlyUnread]);
  useEffect(() => { api.notificationPrefs().then(setPrefs).catch((e) => setError(errorMessage(e))); }, []);

  async function savePrefs() {
    if (!prefs) return;
    setError(""); setNote("");
    const { quiet_start: a, quiet_end: b } = prefs;
    if ((a && !HHMM.test(a)) || (b && !HHMM.test(b))) return setError("Quiet hours are HH:MM, e.g. 22:00");
    if (!!a !== !!b) return setError("Give both a start and an end for quiet hours, or neither");
    try { await api.saveNotificationPrefs({ ...prefs, quiet_start: a || null, quiet_end: b || null }); setNote("Saved."); } catch (e) { setError(errorMessage(e)); }
  }

  return (
    <div className="notif-page">
      <header className="page-head"><div className="titles"><h1>Notifications</h1><span className="muted">{unreadCount} unread</span></div></header>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="ribbon">
        <button type="button" className={`rbtn${onlyUnread ? "" : " primary"}`} aria-pressed={!onlyUnread} onClick={() => setOnlyUnread(false)}>All</button>
        <button type="button" className={`rbtn${onlyUnread ? " primary" : ""}`} aria-pressed={onlyUnread} onClick={() => setOnlyUnread(true)}>Unread</button>
        <button type="button" className="rbtn" disabled={!unreadCount} onClick={async () => { await api.notificationsReadAll(); void load(); }}>Mark all read</button>
      </div>
      <ul className="notif-rows">
        {items.length === 0 && <li className="muted">Nothing here.</li>}
        {items.map((n) => (
          <li key={n.name} className={n.read ? "" : "unread"}>
            <a href={target(n)} onClick={() => { if (!n.read) void api.notificationRead(n.name); }}><strong>{n.subject}</strong></a>
            {n.message && <p>{n.message}</p>}
            <span className="muted">{ago(n.creation)}{n.rule ? ` · ${n.rule}` : ""}</span>
          </li>
        ))}
      </ul>
      {items.length < total && <button type="button" className="rbtn" onClick={() => load(false)}>Load more</button>}

      {prefs && (
        <section className="section" aria-label="Notification settings"><div className="builder-body">
          <h3>How I get notified</h3>
          <label className="chk-inline"><input type="checkbox" checked={prefs.email_enabled} onChange={(e) => setPrefs({ ...prefs, email_enabled: e.target.checked })} /> Send me email</label>
          <div className="field"><label htmlFor="np-digest">Email me</label>
            <select id="np-digest" value={prefs.digest} onChange={(e) => setPrefs({ ...prefs, digest: e.target.value })}>{DIGESTS.map((d) => <option key={d}>{d}</option>)}</select></div>
          <div className="field"><label htmlFor="np-qs">Quiet hours start</label><input id="np-qs" placeholder="22:00" value={prefs.quiet_start ?? ""} onChange={(e) => setPrefs({ ...prefs, quiet_start: e.target.value })} /></div>
          <div className="field"><label htmlFor="np-qe">Quiet hours end</label><input id="np-qe" placeholder="07:00" value={prefs.quiet_end ?? ""} onChange={(e) => setPrefs({ ...prefs, quiet_end: e.target.value })} />
            <small>Urgent notifications ignore quiet hours and digests. Times are the server's time.</small></div>
          <div className="field"><label htmlFor="np-muted">Muted rules (one per line)</label>
            <textarea id="np-muted" rows={3} value={prefs.muted_rules.join("\n")} onChange={(e) => setPrefs({ ...prefs, muted_rules: e.target.value.split("\n") })} /></div>
          <button type="button" className="rbtn primary" onClick={savePrefs}>Save settings</button>
          {note && <span className="success" role="status"> {note}</span>}
        </div></section>
      )}
    </div>
  );
}
