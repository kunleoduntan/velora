import { useEffect, useState } from "react";
import { broadcasts, errorMessage } from "../api";
import type { BroadcastRow, BroadcastSummary } from "../api";
import { Card, Kpi, Tone } from "./centre";

const CHANNELS = ["Email", "SMS", "WhatsApp"] as const;

function BroadcastTable({ rows, empty }: { rows: BroadcastRow[]; empty: string }) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  return <div className="table-wrap"><table><thead><tr><th>Broadcast</th><th>Channel</th><th>Status</th><th className="num">People</th><th className="num">Sent</th><th className="num">Failed</th><th className="num">Opted out</th><th>When</th></tr></thead>
    <tbody>{rows.map(r => <tr key={r.name}><td><a href={`#/app/Broadcast/${encodeURIComponent(r.name)}`}>{r.title}</a><small>{r.name}</small></td><td>{r.channel}</td><td><Tone state={r.status} /></td>
      <td className="num">{r.total_recipients}</td><td className="num">{r.sent_count}</td><td className={`num${r.failed_count ? " brc-bad" : ""}`}>{r.failed_count}</td><td className="num">{r.opted_out_count}</td>
      <td>{(r.scheduled_for ?? r.started_on ?? "").slice(0, 16).replace("T", " ")}</td></tr>)}</tbody></table></div>;
}

/** One place for every mass message: channel readiness, what is running or scheduled, results, and a way to test a gateway. */
export default function BroadcastCentre() {
  const [data, setData] = useState<BroadcastSummary | null>(null), [error, setError] = useState(""), [to, setTo] = useState(""), [channel, setChannel] = useState<string>("Email"), [result, setResult] = useState("");
  const load = () => { setError(""); broadcasts.summary().then(setData).catch(e => setError(errorMessage(e))); };
  useEffect(() => { load(); const t = window.setInterval(load, 30000); return () => window.clearInterval(t); }, []);
  async function test() {
    setResult("");
    try { const r = await broadcasts.testGateway(channel, to); setResult(r.sent ? `Test sent to ${to}.` : `Could not send: ${r.error}`); } catch (e) { setResult(errorMessage(e)); }
  }
  const outbox = data?.outbox ?? {};
  return (
    <div className="panel">
      <div className="page-head">
        <div><h1>Broadcast Centre</h1><p className="muted">Email, SMS and WhatsApp to any audience, with opt-outs, scheduling and delivery tracking.</p></div>
        <div className="head-actions"><a className="rbtn primary" href="#/app/Broadcast/new">New broadcast</a><a className="rbtn" href="#/app/Message%20Template">Templates</a><a className="rbtn" href="#/app/Communication%20Opt-Out">Opt-outs</a></div>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && <>
        <div className="brc-kpis">
          {CHANNELS.map(c => <Kpi key={c} label={`${c} this month`} value={data.by_channel[c]?.sent ?? 0} hint={`${data.by_channel[c]?.broadcasts ?? 0} broadcasts, ${data.by_channel[c]?.failed ?? 0} failed`} />)}
          <Kpi label="Waiting to go out" value={(outbox.Queued ?? 0) + (outbox.Sending ?? 0)} />
          <Kpi label="Failed for good" value={outbox.Dead ?? 0} tone={outbox.Dead ? "bad" : "ok"} />
          <Kpi label="Opted out" value={data.opt_outs} />
        </div>
        <Card title="Channel setup" note="A channel needs its connection details under Notification Centre settings. Send yourself a test before a real broadcast.">
          <ul className="cx-checks">
            {CHANNELS.map(c => <li key={c}><span className={`pill ${data.gateways[c] ? "pill-green" : "pill-orange"}`}>{data.gateways[c] ? "Set up" : "Not set up"}</span> {c}</li>)}
            <li><span className={`pill ${data.gateways.base_url ? "pill-green" : "pill-orange"}`}>{data.gateways.base_url ? "Set" : "Missing"}</span> Public address (needed for unsubscribe links)</li>
          </ul>
          <div className="brc-bar">
            <label>Channel<select value={channel} onChange={e => setChannel(e.target.value)}>{CHANNELS.map(c => <option key={c}>{c}</option>)}</select></label>
            <label>Send a test to<input value={to} onChange={e => setTo(e.target.value)} placeholder={channel === "Email" ? "you@company.com" : "0803 123 4567"} /></label>
            <button className="rbtn" disabled={!to.trim()} onClick={() => void test()}>Send test</button>
          </div>
          {result && <div className="success" role="status">{result}</div>}
        </Card>
        {data.running.length > 0 && <Card title="Sending now"><BroadcastTable rows={data.running} empty="" /></Card>}
        <Card title="Scheduled"><BroadcastTable rows={data.scheduled} empty="Nothing is scheduled." /></Card>
        <Card title="Recent"><BroadcastTable rows={data.recent} empty="No broadcasts yet." /></Card>
      </>}
    </div>
  );
}
