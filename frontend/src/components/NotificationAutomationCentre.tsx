import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

type Settings={base_url?:string;email?:{host?:string;port?:number;user?:string;password_env?:string;from_addr?:string;starttls?:boolean;ssl?:boolean};webhook?:{allow_http?:boolean;allow_private?:boolean;secret_env?:string}};
export default function NotificationAutomationCentre(){
 const [rows,setRows]=useState<any[]>([]),[counts,setCounts]=useState<any>({});
 const [status,setStatus]=useState(""),[settings,setSettings]=useState<Settings>({});
 const [testTo,setTestTo]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
 async function load(){setError("");try{const [d,s]=await Promise.all([api.notificationDeliveries(status),api.notificationSettings()]);setRows(d.items||[]);setCounts(d.counts||{});setSettings(s||{});}catch(e){setError(errorMessage(e));}}
 useEffect(()=>{void load();},[status]);
 async function save(){setBusy(true);setError("");setNotice("");try{const payload:any={...settings};if(!email.host&&!email.from_addr)delete payload.email;if(!webhook.secret_env&&!webhook.allow_http&&!webhook.allow_private)delete payload.webhook;await api.saveNotificationSettings(payload);setNotice("Notification channel settings saved. Secrets remain in environment variables.");await load();}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
 async function retry(name:string){setBusy(true);setError("");try{await api.retryNotificationDelivery(name);setNotice(`Retry queued for ${name}.`);await load();}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
 async function test(){setBusy(true);setError("");setNotice("");try{const r=await api.testNotificationEmail(testTo);setNotice(`Test email sent to ${r.sent}.`);}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
 const email=settings.email||{},webhook=settings.webhook||{};
 return <section className="section"><div className="builder-body">
  <div className="object-studio-heading"><div><h3>Notification & Automation Centre</h3><p className="muted">Configure delivery channels, inspect the durable outbox, and retry failed notifications.</p></div><button className="rbtn" disabled={busy} onClick={()=>void load()}>Refresh</button></div>
  {error&&<div className="error" role="alert">{error}</div>}{notice&&<div className="success" role="status">{notice}</div>}
  <div className="form-grid">{Object.entries(counts).map(([k,v])=><div className="extension-card" key={k}><strong>{String(v)}</strong><small>{k.replaceAll("_"," ")}</small></div>)}</div>
  <div className="extension-card"><h4>Email channel</h4><div className="creator-opts">
   <div className="field"><label>SMTP host</label><input value={email.host||""} onChange={e=>setSettings({...settings,email:{...email,host:e.target.value}})}/></div>
   <div className="field"><label>SMTP port</label><input type="number" value={email.port??587} onChange={e=>setSettings({...settings,email:{...email,port:Number(e.target.value)}})}/></div>
   <div className="field"><label>SMTP username</label><input value={email.user||""} onChange={e=>setSettings({...settings,email:{...email,user:e.target.value}})}/></div>
   <div className="field"><label>Sender email address</label><input value={email.from_addr||""} onChange={e=>setSettings({...settings,email:{...email,from_addr:e.target.value}})}/></div>
   <div className="field"><label>Password environment variable</label><input value={email.password_env||""} placeholder="SMTP_PASSWORD" onChange={e=>setSettings({...settings,email:{...email,password_env:e.target.value}})}/></div>
   <div className="field"><label>Transport security</label><select value={email.ssl?"ssl":email.starttls===false?"none":"starttls"} onChange={e=>setSettings({...settings,email:{...email,ssl:e.target.value==="ssl",starttls:e.target.value==="starttls"}})}><option value="starttls">STARTTLS</option><option value="ssl">Implicit SSL</option><option value="none">None</option></select></div>
  </div></div>
  <div className="extension-card"><h4>Webhook channel security</h4><div className="creator-opts">
   <div className="field"><label>Signing secret environment variable</label><input value={webhook.secret_env||""} placeholder="WEBHOOK_SIGNING_SECRET" onChange={e=>setSettings({...settings,webhook:{...webhook,secret_env:e.target.value}})}/></div>
   <label className="chk-inline"><input type="checkbox" checked={!!webhook.allow_http} onChange={e=>setSettings({...settings,webhook:{...webhook,allow_http:e.target.checked}})}/> Allow non-HTTPS webhooks</label>
   <label className="chk-inline"><input type="checkbox" checked={!!webhook.allow_private} onChange={e=>setSettings({...settings,webhook:{...webhook,allow_private:e.target.checked}})}/> Allow private network targets</label>
   <div className="field"><label>Public application base URL</label><input value={settings.base_url||""} placeholder="https://erp.example.com" onChange={e=>setSettings({...settings,base_url:e.target.value})}/></div>
  </div><p className="muted">Use environment variables for credentials. Do not enter SMTP passwords or signing secrets in this screen.</p><button className="rbtn primary" disabled={busy} onClick={()=>void save()}>Save channel settings</button></div>
  <div className="extension-card"><h4>Test email delivery</h4><div className="field"><label>Recipient email</label><input type="email" value={testTo} onChange={e=>setTestTo(e.target.value)} placeholder="admin@example.com"/></div><button className="rbtn" disabled={busy||!testTo.includes("@")} onClick={()=>void test()}>Send test email</button></div>
  <div className="object-studio-heading"><div><h4>Delivery outbox</h4><p className="muted">Filter delivery attempts and retry eligible failed messages.</p></div><select value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option>{["Queued","Sending","Sent","Failed","Cancelled"].map(x=><option key={x}>{x}</option>)}</select></div>
  <div className="table-wrap"><table className="dgrid"><thead><tr><th>Created</th><th>Rule</th><th>Channel</th><th>Recipient</th><th>Subject</th><th>Status</th><th>Attempts</th><th>Last error</th><th>Action</th></tr></thead><tbody>
   {rows.map(r=><tr key={r.name}><td>{r.creation?new Date(r.creation).toLocaleString():"—"}</td><td>{r.rule}</td><td>{r.channel}</td><td>{r.recipient}</td><td>{r.subject}</td><td><span className={r.status==="Sent"?"status-pill":"muted"}>{r.status}</span></td><td>{r.attempts}</td><td>{r.last_error||"—"}</td><td><button className="rbtn" disabled={busy||r.status!=="Failed"} onClick={()=>void retry(r.name)}>Retry</button></td></tr>)}
   {!rows.length&&<tr><td colSpan={9} className="muted">No delivery records found. Ensure the velora_notify application is installed.</td></tr>}
  </tbody></table></div>
 </div></section>;
}
