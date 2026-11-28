import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type NotificationItem } from "../api";
import { subscribeEvents } from "../events";
import Icon from "../ui/Icon";
import Popover from "../ui/Popover";

export const target = (n: Pick<NotificationItem, "ref_doctype" | "ref_name">) => (n.ref_doctype && n.ref_name ? `#/app/${encodeURIComponent(n.ref_doctype)}/${encodeURIComponent(n.ref_name)}` : "#/notifications");

export function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso.replace(" ", "T")).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** The bell: unread count (refreshed every 30 s), the latest few, mark-as-read. Renders nothing at all if notifications are not installed here. */
export default function NotificationBell({ intervalMs = 30000, liveIntervalMs = 120000 }: { intervalMs?: number; liveIntervalMs?: number }) {
  const [state, setState] = useState<{ unread: number; items: NotificationItem[] } | null>(null);
  const [off, setOff] = useState(false);
  const [live, setLive] = useState(false);
  const load = useCallback(async () => {
    try { const r = await api.notifications({ limit: 8 }); setState({ unread: r.unread, items: r.items }); }
    catch (e) { if (e instanceof ApiError && e.status === 404) setOff(true); }          // not installed (404): hide; any other error: keep the last good state
  }, []);
  // Live: the server pushes "something changed" and we refetch. Polling stays as a slow safety net while connected, and is the main mechanism when it is not.
  useEffect(() => subscribeEvents(() => void load(), setLive), [load]);
  // The effect below also refetches whenever `live` changes, which is what covers a reconnect (events during the gap are lost) and a disconnect.
  useEffect(() => { void load(); const id = setInterval(load, live ? liveIntervalMs : intervalMs); return () => clearInterval(id); }, [load, live, intervalMs, liveIntervalMs]);
  if (off || !state) return null;
  const open = async (n: NotificationItem, close: () => void) => {
    if (!n.read) { try { await api.notificationRead(n.name); } catch { /* the link still works */ } void load(); }
    close();
    window.location.hash = target(n);
  };
  return (
    <Popover align="right" className="notif-pop" trigger={(p) => (
      <button type="button" className="icon-btn notif-bell" aria-label={state.unread ? `Notifications, ${state.unread} unread` : "Notifications"} {...p}>
        <Icon name="bell" />{state.unread > 0 && <span className="notif-badge" aria-hidden="true">{state.unread > 99 ? "99+" : state.unread}</span>}
      </button>)}>
      {(close) => (
        <div className="notif-list">
          <div className="notif-head"><strong>Notifications</strong>
            <button type="button" className="link" disabled={!state.unread} onClick={async () => { await api.notificationsReadAll(); void load(); }}>Mark all read</button></div>
          {state.items.length === 0 && <p className="muted notif-empty">You are all caught up.</p>}
          {state.items.map((n) => (
            <button key={n.name} type="button" className={`notif-item${n.read ? "" : " unread"}${n.priority === "Urgent" || n.priority === "High" ? " urgent" : ""}`} onClick={() => open(n, close)}>
              <span className="notif-subject">{n.subject}</span>
              {n.message && <span className="notif-msg">{n.message.split("\n")[0]}</span>}
              <span className="muted notif-time">{ago(n.creation)}</span>
            </button>
          ))}
          <a className="notif-all" href="#/notifications" onClick={close}>See all and settings</a>
        </div>
      )}
    </Popover>
  );
}
