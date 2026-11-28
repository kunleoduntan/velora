import { day, fmt, portal } from "./portalApi";
import type { Celebration } from "./portalApi";
import { Avatar, Badge, Retry, Skeleton, Table } from "./ui";
import { useResource } from "./useResource";

export type EmployeeView = "home" | "payslips" | "leave" | "holidays";

function Celebrations() {
  const r = useResource(() => portal.celebrations(), []);
  if (r.loading || r.error || !r.data?.length) return null;
  const line = (c: Celebration) => c.kind === "Birthday" ? `${c.first_name}'s birthday` : `${c.first_name}: ${c.years} year${c.years === 1 ? "" : "s"} with us`;
  return <section className="pt-card"><h2>Coming up in the team</h2><ul className="pt-timeline">{r.data.slice(0, 8).map((c, i) => <li key={i}><time>{day(c.date)}</time><span aria-hidden="true">{c.kind === "Birthday" ? "🎂" : "🏆"}</span> {line(c)}</li>)}</ul></section>;
}

function Home() {
  const r = useResource(() => portal.employeeOverview(), []);
  if (r.error) return <Retry error={r.error} onRetry={r.reload} />;
  if (!r.data) return <Skeleton rows={4} />;
  const { profile: p, latest_payslip: slip, leave, who } = r.data;
  return <>
    <h1>Welcome, {who.name}</h1>
    <section className="pt-card pt-hero"><Avatar name={p.employee_name} size={64} />
      <div><h2>{p.employee_name}</h2><p className="pt-muted">{[p.designation, p.department, p.branch].filter(Boolean).join(" · ") || p.code}</p>
        <p className="pt-muted">{p.service_years != null ? `${p.service_years} years with us (since ${day(p.date_of_joining)})` : ""}{p.manager ? ` · Reports to ${p.manager}` : ""}</p></div></section>
    <div className="pt-kpis">
      <div className="pt-kpi"><span>Latest net pay</span><strong>{slip ? fmt(slip.net_pay, slip.currency) : "—"}</strong><small>{slip ? `${day(slip.period_start)} to ${day(slip.period_end)}` : "No payslip yet"}</small></div>
      <div className="pt-kpi"><span>Leave requests</span><strong>{leave.requests}</strong><small>{leave.pending} waiting for approval</small></div>
      <div className="pt-kpi"><span>Work email</span><strong className="pt-small">{p.email || "—"}</strong><small>{p.work_location || p.employee_type || ""}</small></div>
    </div>
    <Celebrations /></>;
}

function Payslips() {
  const r = useResource(() => portal.payslips(), []);
  return <><h1>Payslips</h1>{r.error && <Retry error={r.error} onRetry={r.reload} />}{r.loading && <Skeleton rows={4} />}
    {r.data && <><Table rows={r.data} empty="No payslips have been issued yet." cols={[
      { head: "Period", cell: s => `${day(s.period_start)} to ${day(s.period_end)}` }, { head: "Gross", num: true, cell: s => fmt(s.gross_earnings, s.currency) },
      { head: "Deductions", num: true, cell: s => fmt(s.employee_deductions, s.currency) }, { head: "Net pay", num: true, cell: s => <strong>{fmt(s.net_pay, s.currency)}</strong> },
      { head: "Status", cell: s => <Badge s={s.status} /> }]} />
      {r.data.length > 0 && <button className="pt-btn" onClick={() => window.print()}>Print</button>}</>}</>;
}

function Leave() {
  const r = useResource(() => portal.leave(), []);
  return <><h1>My leave</h1>{r.error && <Retry error={r.error} onRetry={r.reload} />}{r.loading && <Skeleton rows={4} />}
    {r.data && <Table rows={r.data} empty="You have not requested any leave." cols={[
      { head: "Type", cell: l => l.leave_type }, { head: "From", cell: l => day(l.from_date) }, { head: "To", cell: l => day(l.to_date) }, { head: "Days", num: true, cell: l => String(l.total_days) },
      { head: "Status", cell: l => <Badge s={l.workflow_status || "Draft"} /> }, { head: "Reason", cell: l => l.reason || "—" }]} />}
    <p className="pt-muted">To request leave, use the HR desk or ask your manager.</p></>;
}

function Holidays() {
  const r = useResource(() => portal.holidays(), []);
  return <><h1>Upcoming holidays</h1>{r.error && <Retry error={r.error} onRetry={r.reload} />}{r.loading && <Skeleton rows={4} />}
    {r.data && (r.data.length ? <section className="pt-card"><ul className="pt-timeline">{r.data.map(h => <li key={h.date}><time>{day(h.date)}</time><span aria-hidden="true">🌴</span> {new Date(`${h.date}T00:00:00`).toLocaleDateString(undefined, { weekday: "long" })}</li>)}</ul></section>
      : <p className="pt-muted">No upcoming holidays are listed.</p>)}</>;
}

export default function EmployeePages({ view }: { view: EmployeeView }) {
  return view === "payslips" ? <Payslips /> : view === "leave" ? <Leave /> : view === "holidays" ? <Holidays /> : <Home />;
}
