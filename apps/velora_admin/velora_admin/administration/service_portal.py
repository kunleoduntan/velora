"""Employee-facing service portal API logic, reusing the request lifecycle."""
from velora import get_list, get_doc, new_doc, throw
from velora.permissions import get_session
from . import approval_service

def catalog():
 rows=get_list("Service",filters={"is_active":1},fields=["name","service_name","service_code","category","description","instructions","request_type","sla_hours","priority_default","allow_attachments","fields"],limit=1000,ignore_permissions=True)
 return {"categories":sorted(set(r.get("category") for r in rows if r.get("category"))),"services":rows}

def create_service_request(payload):
 if not payload.get("service"):throw("Service is required.")
 service=get_doc("Service",payload["service"],ignore_permissions=True)
 if not service or not service.is_active:throw("Service is unavailable.")
 payload=dict(payload);payload["request_type"]=service.request_type;payload["priority"]=payload.get("priority") or service.priority_default
 form_data=payload.get("form_data") or payload.get("service_form_data") or {}
 if not isinstance(form_data,dict):throw("Service form data must be an object.")
 for field in getattr(service,"fields",[]) or []:
  fieldname=getattr(field,"fieldname",None);label=getattr(field,"label",None) or fieldname
  if getattr(field,"required",0) and (fieldname not in form_data or form_data.get(fieldname) in (None,"",[])):
   throw(f"Required service field is missing: {label}")
 if payload.get("attachment_reference") and not getattr(service,"allow_attachments",0):throw("Attachments are not permitted for this service.")
 payload["service_form_data"]=form_data
 if not payload.get("description"):payload["description"]=str(payload.get("summary") or service.service_name)
 payload["service"]=service.name
 return approval_service.create_request(payload)

def my_requests():
 session=get_session();person=approval_service._current_person_link(session)
 if not person: return {"items":[]}
 rows=get_list("Request",filters={"requester":person},fields=["name","service","request_type","status","priority","creation","sla_status","sla_due_datetime","description"],limit=1000,ignore_permissions=True)
 return {"items":rows}

def request_progress(name):
 detail=approval_service.request_detail(name)
 return {"name":detail["name"],"status":detail["status"],"priority":detail.get("priority"),"sla_status":detail.get("sla_status"),"sla_due_datetime":detail.get("sla_due_datetime"),"approval_history":detail.get("approval_history"),"description":detail.get("description")}

def cancel_request(name):
 doc=get_doc("Request",name);session=get_session();person=approval_service._current_person_link(session)
 if str(doc.requester or "") not in (session.user,person):throw("You can only cancel your own request.")
 if doc.status!="Draft" and doc.status!="Pending Approval":throw("Only Draft or Pending Approval requests can be cancelled.")
 if doc.status=="Pending Approval" and doc.service:
  try:
   service=get_doc("Service",doc.service,ignore_permissions=True)
   if not getattr(service,"requester_can_cancel",1):throw("This service does not permit requester cancellation after submission.")
  except Exception as e:
   if "does not permit" in str(e):raise
 doc.status="Cancelled"
 if int(doc.docstatus or 0)==1:
  # Use cancel lifecycle where supported; fallback to controlled status transition.
  try:doc.cancel()
  except Exception:doc.save(ignore_permissions=True)
 else:doc.save(ignore_permissions=True)
 return {"name":doc.name,"status":doc.status}


def add_request_comment(name, payload):
 """Append a requester-visible comment to the existing request comments table."""
 doc=get_doc("Request",name);session=get_session();person=approval_service._current_person_link(session)
 if str(doc.requester or "") not in (session.user,person):throw("Only the requester can add a portal comment.")
 comment=str(payload.get("comment") or "").strip()
 if not comment:throw("Comment cannot be empty.")
 from datetime import datetime
 doc.append("request_comments",{"comment_by":session.user,"comment_on":datetime.now().isoformat(timespec="seconds"),"comment":comment,"visibility":"Requester and Staff","attachment_reference":payload.get("attachment_reference")})
 doc.save(ignore_permissions=True)
 return {"name":doc.name,"comment_count":len(doc.request_comments or [])}


def request_feedback(name, payload):
 """Record one requester rating against the completed request; request unique constraint prevents duplicate feedback."""
 from datetime import datetime
 session=get_session(); person=approval_service._current_person_link(session); doc=get_doc("Request",name)
 if str(doc.requester or "") not in (session.user,person):throw("Only the requester can rate their own request.")
 if doc.status not in ("Completed","Closed"):throw("Feedback is available after service completion.")
 service=get_doc("Service",doc.service,ignore_permissions=True) if getattr(doc,"service",None) else None
 if service and not getattr(service,"quality_rating_enabled",1):throw("Feedback is disabled for this service.")
 rating=int(payload.get("rating") or 0)
 if rating<1 or rating>5:throw("Rating must be between 1 and 5.")
 existing=get_list("Service Feedback",filters={"request":name},fields=["name"],limit=1,ignore_permissions=True)
 if existing:throw("Feedback has already been submitted for this request.")
 quality="Positive" if rating>=4 else "Needs Improvement" if rating<=2 else "Neutral"
 feedback=new_doc("Service Feedback",request=name,service=getattr(doc,"service",None),requester=person,rating=rating,feedback=str(payload.get("feedback") or "").strip(),submitted_on=datetime.now().isoformat(timespec="seconds"),service_quality_flag=quality)
 feedback.insert(ignore_permissions=True)
 return {"name":feedback.name,"request":name,"rating":rating,"quality_flag":quality}


def staff_comment(name,payload):
 """Staff collaboration uses the existing request_comments child table, with explicit visibility."""
 from datetime import datetime
 session=get_session(); roles=set(getattr(session,"roles",[]) or [])
 allowed={"System Manager","Administration Manager","Administrative Manager","Administrative Officer","Service Desk Agent"}
 if session.user!="Administrator" and not roles.intersection(allowed):throw("Service staff permission required.")
 doc=get_doc("Request",name,ignore_permissions=True)
 comment=str(payload.get("comment") or "").strip()
 if not comment:throw("Comment cannot be empty.")
 visibility=payload.get("visibility") or "Requester and Staff"
 if visibility not in ("Requester and Staff","Staff Only"):throw("Invalid comment visibility.")
 doc.append("request_comments",{"comment_by":session.user,"comment_on":datetime.now().isoformat(timespec="seconds"),"comment":comment,"visibility":visibility,"attachment_reference":payload.get("attachment_reference")})
 doc.save(ignore_permissions=True)
 return {"name":doc.name,"comment_count":len(doc.request_comments or []),"visibility":visibility}


def request_timeline(name):
 """Unified timeline read assembled from existing request, approval, comments and fulfilment records."""
 session=get_session();person=approval_service._current_person_link(session);doc=get_doc("Request",name,ignore_permissions=True)
 if str(doc.requester or "") not in (session.user,person):
  roles=set(getattr(session,"roles",[]) or []);allowed={"System Manager","Administration Manager","Administrative Manager","Administrative Officer","Service Desk Agent"}
  if session.user!="Administrator" and not roles.intersection(allowed):throw("Not permitted to view this request timeline.")
 items=[]
 items.append({"type":"request","date":getattr(doc,"creation",None),"title":"Request created","description":getattr(doc,"description",None)})
 for row in getattr(doc,"approval_history",[]) or []:
  items.append({"type":"approval","date":getattr(row,"action_on",None),"title":f"Approval level {getattr(row,'level_no','')}: {getattr(row,'status','Pending')}","description":getattr(row,"comments",None)})
 for row in getattr(doc,"request_comments",[]) or []:
  if str(getattr(row,"visibility", "Requester and Staff"))=="Staff Only" and str(doc.requester or "") in (session.user,person):continue
  items.append({"type":"comment","date":getattr(row,"comment_on",None),"title":f"Comment by {getattr(row,'comment_by','')}","description":getattr(row,"comment",None),"visibility":getattr(row,"visibility",None),"attachment_reference":getattr(row,"attachment_reference",None)})
 try:
  assignments=get_list("Request Fulfilment",filters={"request":name},fields=["name","status","assigned_to","assigned_team","started_on","completed_on","creation"],limit=20,ignore_permissions=True)
  for a in assignments:items.append({"type":"fulfilment","date":a.get("started_on") or a.get("creation"),"title":"Fulfilment: "+str(a.get("status")),"description":f"Assigned to {a.get('assigned_to') or 'Unassigned'} / {a.get('assigned_team') or 'Unassigned team'}"})
 except Exception:pass
 items.sort(key=lambda x:str(x.get("date") or ""))
 return {"name":name,"items":items}


def portal_search(query="",category=None):
 data=catalog();q=str(query or "").strip().lower()
 items=[s for s in data["services"] if (not category or s.get("category")==category) and (not q or q in str(s.get("service_name","")).lower() or q in str(s.get("description","")).lower() or q in str(s.get("service_code","")).lower())]
 return {"categories":data["categories"],"items":items}


def portal_html():
 """Lightweight first-party portal UI backed entirely by the existing service/request APIs."""
 return r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Employee Service Portal</title><style>
:root{font-family:Inter,system-ui,Segoe UI,sans-serif;color:#17233a;background:#f5f7fb}body{margin:0}.shell{max-width:1180px;margin:auto;padding:24px}.hero{background:linear-gradient(120deg,#123d78,#2463b7);color:white;border-radius:18px;padding:26px 30px;box-shadow:0 8px 28px #163b6b22}.hero h1{margin:0 0 8px}.nav{display:flex;gap:10px;margin:20px 0}.nav button,.button{border:0;border-radius:9px;padding:10px 15px;background:#215ca8;color:white;cursor:pointer}.nav button.secondary{background:#e5edf8;color:#174c8b}.search{display:flex;gap:10px;margin:16px 0}.search input{flex:1;border:1px solid #d3dce9;border-radius:10px;padding:12px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:15px}.card{background:white;border:1px solid #e4eaf2;border-radius:13px;padding:17px;box-shadow:0 2px 7px #13294b08}.card h3{margin:0 0 8px}.muted{color:#68778b;font-size:14px}.pill{display:inline-block;padding:4px 8px;background:#e9f2ff;border-radius:999px;font-size:12px;color:#205998}.hidden{display:none}.formrow{margin:10px 0}.formrow label{display:block;font-size:13px;font-weight:600;margin-bottom:5px}.formrow input,.formrow select,.formrow textarea{width:100%;box-sizing:border-box;padding:9px;border:1px solid #d2dbe7;border-radius:8px}.modal{background:white;border:1px solid #dce5f0;border-radius:14px;padding:20px;margin-top:16px}.timeline{border-left:2px solid #d7e4f4;margin:12px 0;padding-left:16px}.event{margin:0 0 14px}.status{font-weight:700}.error{color:#b42318}.success{color:#18764a}@media(max-width:640px){.shell{padding:12px}.hero{padding:20px}.nav{flex-wrap:wrap}}
</style></head><body><div class="shell"><header class="hero"><h1>Employee Service Portal</h1><div>Find a service, submit a request and follow it through to completion.</div></header><nav class="nav"><button id="catalogTab">Service Catalogue</button><button id="requestsTab" class="secondary">My Requests</button></nav><section id="catalog"><div class="search"><input id="q" placeholder="Search services…"><select id="category"><option value="">All categories</option></select></div><div id="services" class="grid"></div></section><section id="requests" class="hidden"><div id="myRequests" class="grid"></div></section><section id="detail" class="modal hidden"></section><section id="formModal" class="modal hidden"></section><div id="message"></div></div><script>
const api='/api/admin/service-portal';let services=[],activeRequest=null;
async function get(url){const r=await fetch(url,{credentials:'same-origin'});if(!r.ok)throw new Error(await r.text());return r.json()}
async function post(url,data){const r=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})});if(!r.ok)throw new Error(await r.text());return r.json()}
function msg(t,cls=''){document.getElementById('message').innerHTML=t?`<p class="${cls}">${t}</p>`:''}
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function switchTab(tab){document.getElementById('catalog').classList.toggle('hidden',tab!=='catalog');document.getElementById('requests').classList.toggle('hidden',tab!=='requests');document.getElementById('detail').classList.add('hidden');document.getElementById('formModal').classList.add('hidden')}
async function loadCatalog(){const data=await get(api+'/catalog');services=data.services||[];let cats=[...new Set(data.categories||[])];document.getElementById('category').innerHTML='<option value="">All categories</option>'+cats.map(c=>`<option>${esc(c)}</option>`).join('');renderServices()}
function renderServices(){let q=document.getElementById('q').value.toLowerCase(),cat=document.getElementById('category').value;let items=services.filter(s=>(!cat||s.category===cat)&&(!q||`${s.service_name} ${s.description||''} ${s.service_code}`.toLowerCase().includes(q)));document.getElementById('services').innerHTML=items.map(s=>`<article class="card"><span class="pill">${esc(s.category)}</span><h3>${esc(s.service_name)}</h3><p class="muted">${esc(s.description||'')}</p><p class="muted">Expected SLA: ${esc(s.sla_hours||'—')} hours</p><button class="button" onclick="openService('${esc(s.name)}')">Request Service</button></article>`).join('')||'<p>No matching services.</p>'}
async function openService(name){const s=await get(api+'/catalog');let svc=(s.services||[]).find(x=>x.name===name);if(!svc)return;let detail=await get(api+'/services/'+encodeURIComponent(name));svc=detail;let fields=svc.fields||[];let form=fields.map(f=>fieldHtml(f)).join('');document.getElementById('formModal').innerHTML=`<h2>${esc(svc.service_name)}</h2><p>${esc(svc.instructions||svc.description||'')}</p><form id="requestForm"><div class="formrow"><label>Request summary *</label><input name="summary" required></div><div class="formrow"><label>Description</label><textarea name="description" rows="3"></textarea></div>${form}<button class="button">Submit Request</button><button type="button" class="button" onclick="closeForm()" style="background:#66758b">Cancel</button></form>`;document.getElementById('formModal').classList.remove('hidden');document.getElementById('requestForm').onsubmit=async e=>{e.preventDefault();let fd=new FormData(e.target),form_data={};fields.forEach(f=>{let v=fd.get(f.fieldname);if(f.fieldtype==='Check')v=fd.get(f.fieldname)==='on';if(v!==null&&v!=='')form_data[f.fieldname]=v});try{let result=await post(api+'/requests',{service:name,summary:fd.get('summary'),description:fd.get('description'),form_data});if(result.name){await post('/api/admin/requests/'+encodeURIComponent(result.name)+'/submit',{});}msg('Request submitted: '+esc(result.name),'success');closeForm();loadRequests()}catch(err){msg(esc(err.message),'error')}}}
function fieldHtml(f){let name=esc(f.fieldname),label=esc(f.label||f.fieldname),required=f.required?'required':'';let type=f.fieldtype||'Data';if(type==='Select'){let opts=(f.options||'').split('\n').filter(Boolean);return `<div class="formrow"><label>${label}${f.required?' *':''}</label><select name="${name}" ${required}><option value="">Select…</option>${opts.map(o=>`<option>${esc(o)}</option>`).join('')}</select></div>`}if(type==='Text'||type==='Small Text')return `<div class="formrow"><label>${label}</label><textarea name="${name}" ${required}></textarea></div>`;if(type==='Check')return `<div class="formrow"><label><input type="checkbox" name="${name}"> ${label}</label></div>`;let input=({Date:'date',Datetime:'datetime-local',Int:'number',Float:'number',Currency:'number'})[type]||'text';return `<div class="formrow"><label>${label}${f.required?' *':''}</label><input name="${name}" type="${input}" ${required}></div>`}
function closeForm(){document.getElementById('formModal').classList.add('hidden')}
async function loadRequests(){let data=await get(api+'/requests/my');let items=data.items||[];document.getElementById('myRequests').innerHTML=items.map(r=>`<article class="card"><h3>${esc(r.name)}</h3><p>${esc(r.description||'')}</p><span class="pill">${esc(r.status)}</span><p class="muted">SLA: ${esc(r.sla_status||'—')}</p><button class="button" onclick="showProgress('${esc(r.name)}')">View Progress</button>${['Draft','Pending Approval'].includes(r.status)?`<button class="button" style="background:#a13a45" onclick="cancelReq('${esc(r.name)}')">Cancel</button>`:''}</article>`).join('')||'<p>You have no requests yet.</p>'}
async function showProgress(name){activeRequest=name;let data=await get(api+'/requests/'+encodeURIComponent(name)+'/progress');let timeline=await get(api+'/requests/'+encodeURIComponent(name)+'/timeline');document.getElementById('detail').innerHTML=`<h2>${esc(name)} — ${esc(data.status)}</h2><p>${esc(data.description||'')}</p><div class="timeline">${(timeline.items||[]).map(x=>`<div class="event"><b>${esc(x.title)}</b><div class="muted">${esc(x.date||'')}</div><div>${esc(x.description||'')}</div></div>`).join('')}</div><form id="commentForm"><div class="formrow"><label>Comment</label><textarea name="comment" required></textarea></div><button class="button">Add Comment</button></form>${['Completed','Closed'].includes(data.status)?`<form id="feedbackForm"><h3>Rate this service</h3><div class="formrow"><label>Rating (1–5)</label><select name="rating" required><option value="">Choose</option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select></div><div class="formrow"><label>Feedback</label><textarea name="feedback"></textarea></div><button class="button">Submit Feedback</button></form>`:''}`;document.getElementById('detail').classList.remove('hidden');document.getElementById('commentForm').onsubmit=async e=>{e.preventDefault();try{await post(api+'/requests/'+encodeURIComponent(name)+'/comments',{comment:new FormData(e.target).get('comment')});showProgress(name)}catch(err){msg(esc(err.message),'error')}};let ff=document.getElementById('feedbackForm');if(ff)ff.onsubmit=async e=>{e.preventDefault();let fd=new FormData(e.target);try{await post(api+'/requests/'+encodeURIComponent(name)+'/feedback',{rating:fd.get('rating'),feedback:fd.get('feedback')});msg('Thank you for your feedback.','success');ff.remove()}catch(err){msg(esc(err.message),'error')}}}
async function cancelReq(name){if(!confirm('Cancel this request?'))return;try{await post(api+'/requests/'+encodeURIComponent(name)+'/cancel',{});loadRequests()}catch(err){msg(esc(err.message),'error')}}
document.getElementById('catalogTab').onclick=()=>switchTab('catalog');document.getElementById('requestsTab').onclick=()=>{switchTab('requests');loadRequests()};document.getElementById('q').oninput=renderServices;document.getElementById('category').onchange=renderServices;loadCatalog().catch(e=>msg(esc(e.message),'error'));
</script></body></html>'''


def service_detail(name):
 service=get_doc("Service",name,ignore_permissions=True)
 if not service or not getattr(service,"is_active",0):throw("Service is unavailable.")
 return {k:getattr(service,k,None) for k in ("name","service_name","service_code","category","description","instructions","request_type","sla_hours","priority_default","allow_attachments","fields")}
