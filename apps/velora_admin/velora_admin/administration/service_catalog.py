"""Administrative service catalogue, templates and service operations metrics."""
from datetime import datetime, date, timedelta
from velora import get_doc, get_list, new_doc, throw
from velora.permissions import get_session

ADMIN_ROLES = {"System Manager", "Administration Manager", "Administrative Manager"}
def _admin():
 s=get_session()
 if s.user != "Administrator" and not (set(getattr(s,"roles",[]) or []) & ADMIN_ROLES): throw("Administrative Manager access is required.")
 return s

def catalog():
 items=get_list("Service", filters={"is_active":1}, fields=["name","service_name","service_code","category","request_type","default_department","default_team","sla_hours","priority_default","requires_evidence","allow_attachments","description","instructions"],limit=1000,ignore_permissions=True)
 return {"items":items}

def service_detail(name):
 _admin(); return get_doc("Service",name,ignore_permissions=True).as_dict()

def service_create(payload):
 _admin(); doc=new_doc("Service",**{k:v for k,v in payload.items() if k in ("service_name","service_code","category","request_type","default_department","default_team","sla_hours","priority_default","requires_evidence","allow_attachments","is_active","description","instructions","fields","service_owner","service_status","review_frequency_months","last_reviewed_on","next_review_date","governance_notes","quality_rating_enabled")})
 doc.insert(ignore_permissions=True); return doc.as_dict()

def service_update(name,payload):
 _admin(); doc=get_doc("Service",name,ignore_permissions=True)
 allowed=("service_name","service_code","category","request_type","default_department","default_team","sla_hours","priority_default","requires_evidence","allow_attachments","is_active","description","instructions","fields","service_owner","service_status","review_frequency_months","last_reviewed_on","next_review_date","governance_notes","quality_rating_enabled")
 for k in allowed:
  if k in payload: setattr(doc,k,payload[k])
 doc.save(ignore_permissions=True); return doc.as_dict()

def templates(service=None):
 _admin(); filters={"is_active":1}
 if service: filters["service"]=service
 return {"items":get_list("Fulfilment Template",filters=filters,fields=["name","template_name","service","sla_hours_override","completion_notes_required","evidence_required","description"],limit=1000,ignore_permissions=True)}

def template_create(payload):
 _admin(); allowed=("template_name","service","is_active","sla_hours_override","completion_notes_required","evidence_required","tasks","description")
 doc=new_doc("Fulfilment Template",**{k:v for k,v in payload.items() if k in allowed}); doc.insert(ignore_permissions=True); return doc.as_dict()

def template_update(name,payload):
 _admin(); doc=get_doc("Fulfilment Template",name,ignore_permissions=True)
 for k in ("template_name","service","is_active","sla_hours_override","completion_notes_required","evidence_required","tasks","description"):
  if k in payload:setattr(doc,k,payload[k])
 doc.save(ignore_permissions=True); return doc.as_dict()

def apply_template(assignment, request_doc):
 """Auto-apply the active template for the request's mapped service, idempotently."""
 try:
  kinds=get_list("Service",filters={"request_type":request_doc.request_type,"is_active":1},fields=["name","sla_hours","requires_evidence"],limit=10,ignore_permissions=True)
  if not kinds:return {"applied":False,"reason":"No mapped active service"}
  service=kinds[0]
  templates_rows=get_list("Fulfilment Template",filters={"service":service["name"],"is_active":1},fields=["name"],limit=10,ignore_permissions=True)
  if not templates_rows:return {"applied":False,"reason":"No active template"}
  template=get_doc("Fulfilment Template",templates_rows[0]["name"],ignore_permissions=True)
  existing=list(getattr(assignment,"tasks",[]) or [])
  if existing:return {"applied":False,"reason":"Tasks already exist"}
  today=date.today()
  for row in sorted(template.tasks or [],key=lambda t:(getattr(t,"sequence",10) or 10)):
   due=today+timedelta(days=int(getattr(row,"offset_days",0) or 0))
   assignment.append("tasks",{"task_title":row.task_title,"assigned_to":getattr(row,"default_assignee",None) or assignment.assigned_to,"assigned_team":getattr(row,"default_team",None) or assignment.assigned_team,"due_date":due.isoformat(),"status":"Open","depends_on_sequence":getattr(row,"depends_on_sequence",None),"sequence":getattr(row,"sequence",10),"evidence_required":getattr(row,"evidence_required",0),"is_required":getattr(row,"is_required",1)})
  assignment.save(ignore_permissions=True)
  return {"applied":True,"template":template.name,"task_count":len(template.tasks or [])}
 except Exception as exc:
  # Do not break approval->fulfilment creation; admins can recover from template errors.
  return {"applied":False,"reason":str(exc)}

def dashboard():
 _admin(); today=date.today()
 assignments=get_list("Request Fulfilment",fields=["name","request","status","assigned_to","assigned_team","due_date","progress_percent","started_on","completed_on","creation"],limit=10000,ignore_permissions=True)
 requests=get_list("Request",fields=["name","request_type","service","department","status","sla_status","creation","sla_due_datetime"],limit=10000,ignore_permissions=True)
 statuses={}; teams={}; users={}; unassigned=overdue=completed=total_hours=duration_count=0; service_counts={}; department_counts={}; sla_ok=0
 for a in assignments:
  st=a.get("status") or "Unknown"; statuses[st]=statuses.get(st,0)+1
  if st not in ("Completed","Closed","Cancelled"):
   if not a.get("assigned_to"):unassigned+=1
   if a.get("due_date") and str(a["due_date"])[:10]<today.isoformat():overdue+=1
   team=a.get("assigned_team") or "Unassigned Team"; teams[team]=teams.get(team,0)+1
   user=a.get("assigned_to") or "Unassigned"; users[user]=users.get(user,0)+1
  if st in ("Completed","Closed"):
   completed+=1
   try:
    start=datetime.fromisoformat(str(a.get("started_on"))[:19]); end=datetime.fromisoformat(str(a.get("completed_on"))[:19]); total_hours+=(end-start).total_seconds()/3600; duration_count+=1
   except Exception:pass
 for r in requests:
  typ=r.get("service") or r.get("request_type") or "Unspecified"; service_counts[typ]=service_counts.get(typ,0)+1
  dep=r.get("department") or "Unassigned"; department_counts[dep]=department_counts.get(dep,0)+1
  if r.get("sla_status") != "Overdue":sla_ok+=1
 return {"kpis":{"total_requests":len(requests),"total_fulfilment":len(assignments),"active_fulfilment":sum(statuses.get(x,0) for x in ("Assigned","In Progress","Blocked")),"unassigned":unassigned,"overdue":overdue,"completed":completed,"sla_compliance_percent":round(sla_ok*100/max(len(requests),1),1),"average_fulfilment_hours":round(total_hours/duration_count,1) if duration_count else None},"fulfilment_statuses":statuses,"workload_by_team":teams,"workload_by_user":users,"requests_by_service":service_counts,"requests_by_department":department_counts}


def service_governance(name, payload=None):
 """Service owner/review governance controls on the existing service record."""
 _admin(); doc=get_doc("Service",name,ignore_permissions=True)
 if payload:
  allowed=("service_owner","service_status","review_frequency_months","last_reviewed_on","next_review_date","governance_notes","quality_rating_enabled")
  for key in allowed:
   if key in payload:setattr(doc,key,payload[key])
  doc.save(ignore_permissions=True)
 return {k:getattr(doc,k,None) for k in ("name","service_name","service_owner","service_status","review_frequency_months","last_reviewed_on","next_review_date","governance_notes","quality_rating_enabled")}


def service_governance_review_due():
 """Return service governance records due for review, without creating a duplicate review engine."""
 _admin(); today=date.today().isoformat()
 rows=get_list("Service",fields=["name","service_name","service_owner","service_status","last_reviewed_on","next_review_date","review_frequency_months"],limit=5000,ignore_permissions=True)
 due=[r for r in rows if r.get("service_status") in ("Active","Under Review") and r.get("next_review_date") and str(r["next_review_date"])[:10]<=today]
 return {"as_of":today,"due_count":len(due),"items":due}


def mark_service_reviewed(name, notes=None):
 """Complete a governance review and schedule the next review from configured frequency."""
 _admin();doc=get_doc("Service",name,ignore_permissions=True)
 today=date.today();months=max(int(getattr(doc,"review_frequency_months",12) or 12),1)
 # Month arithmetic with end-of-month clipping.
 year=today.year+(today.month-1+months)//12;month=(today.month-1+months)%12+1
 import calendar
 day=min(today.day,calendar.monthrange(year,month)[1]);next_date=date(year,month,day)
 doc.last_reviewed_on=today.isoformat();doc.next_review_date=next_date.isoformat();doc.service_status="Active"
 if notes is not None:doc.governance_notes=str(notes)
 doc.save(ignore_permissions=True)
 return {"name":name,"last_reviewed_on":doc.last_reviewed_on,"next_review_date":doc.next_review_date,"service_status":doc.service_status}
