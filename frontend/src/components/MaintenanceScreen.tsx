import { useEffect, useRef } from "react";

export interface MaintenanceInfo { kind: "Maintenance" | "UpgradePending"; message: string }

/** Shown while the server is being upgraded (or needs an upgrade). It polls /api/health and carries on by itself when the system is back. */
export default function MaintenanceScreen({ info, intervalMs = 4000, onRecovered = () => window.location.reload() }: {
  info: MaintenanceInfo; intervalMs?: number; onRecovered?: () => void;
}) {
  const done = useRef(false);
  useEffect(() => {
    const tick = async () => {
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (res.ok && !done.current) { done.current = true; onRecovered(); }
      } catch { /* server restarting: keep trying */ }
    };
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, onRecovered]);
  const pending = info.kind === "UpgradePending";
  return (
    <div className="maintenance" role="alert" aria-live="assertive">
      <div className="spinner" aria-hidden="true" />
      <h1>{pending ? "An upgrade is needed" : "Upgrading Velora"}</h1>
      <p>{info.message || (pending ? "An administrator needs to finish the upgrade." : "This page will reload by itself when it is ready.")}</p>
      <p className="muted">{pending ? "Ask your administrator to run `velora upgrade`. This page keeps checking." : "Your data is safe. This usually takes a minute or two."}</p>
    </div>
  );
}
