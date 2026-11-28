"""Service lifecycle, business-calendar SLA calculations, notifications and escalations.
Uses existing Request SLA fields and service metadata; no parallel SLA ledger.
"""
from datetime import datetime, timedelta, date, time
from velora import get_doc, get_list, new_doc
from velora.meta.registry import registry
from velora.permissions import get_session

ADMIN_ROLES={"System Manager","Administration Manager","Administrative Manager"}
def _admin():
 s=get_session()
 if s.user!="Administrator" and not set(getattr(s,"roles",[]) or []).intersection(ADMIN_ROLES):
  raise PermissionError("Administrative Manager access is required")
 return s

def _parse_time(value, default):
 try:return time.fromisoformat(str(value))
 except Exception:return default

def business_due(start, hours, calendar=None):
 """Calculate due datetime. Without a calendar, uses elapsed hours. Calendar uses configured work windows."""
 start=datetime.fromisoformat(str(start)) if not isinstance(start,datetime) else start
 remaining=max(float(hours or 0),0)*3600
 if not calendar or not registry.exists("Business Calendar"):
  return start+timedelta(seconds=remaining)
 try:
  cal=get_doc("Business Calendar",calendar,ignore_permissions=True)
  days=getattr(cal,"working_days","Monday-Friday")
  allowed={0,1,2,3,4} if days=="Monday-Friday" else set(range(6)) if days=="Monday-Saturday" else set(range(7))
  holidays={str(getattr(x,"holiday_date",None))[:10] for x in getattr(cal,"holidays",[]) or []}
  st=_parse_time(getattr(cal,"start_time",None),time(9,0)); en=_parse_time(getattr(cal,"end_time",None),time(17,0))
  cursor=start
  while remaining>0:
   if cursor.weekday() not in allowed or cursor.date().isoformat() in holidays:
    cursor=(cursor+timedelta(days=1)).replace(hour=st.hour,minute=st.minute,second=0,microsecond=0);continue
   opening=cursor.replace(hour=st.hour,minute=st.minute,second=0,microsecond=0); closing=cursor.replace(hour=en.hour,minute=en.minute,second=0,microsecond=0)
   if cursor<opening:cursor=opening
   if cursor>=closing:
    cursor=(cursor+timedelta(days=1)).replace(hour=st.hour,minute=st.minute,second=0,microsecond=0);continue
   available=(closing-cursor).total_seconds()
   if remaining<=available:return cursor+timedelta(seconds=remaining)
   remaining-=available;cursor=(cursor+timedelta(days=1)).replace(hour=st.hour,minute=st.minute,second=0,microsecond=0)
  return cursor
 except Exception:
  return start+timedelta(hours=hours)

def _notify(user,subject,message,doctype,name):
 if not user or not registry.exists("Notification Log"):return False
 try:
  fields={f.fieldname for f in registry.get("Notification Log").fields}
  payload={k:v for k,v in {"user":user,"subject":subject,"message":message,"ref_doctype":doctype,"ref_name":name,"document_type":doctype,"document_name":name,"type":"Alert"}.items() if k in fields}
  if payload:new_doc("Notification Log",**payload).insert(ignore_permissions=True);return True
 except Exception:pass
 return False

def notify_requester(doc,subject,message):
 try:
  person=get_doc("Person",doc.requester,ignore_permissions=True)
  user=getattr(person,"user_account",None) or getattr(person,"email",None)
 except Exception:user=None
 return _notify(user,subject,message,"Request",doc.name)

def notify_assignee(assignment,subject,message):
 return _notify(getattr(assignment,"assigned_to",None),subject,message,"Request Fulfilment",assignment.name)

def due_warning(doc, percent=80):
 """Warning threshold based on creation and due time, only once per request."""
 due=getattr(doc,"sla_due_datetime",None);created=getattr(doc,"creation",None)
 if not due or not created:return False
 try:
  due=datetime.fromisoformat(str(due));created=datetime.fromisoformat(str(created));now=datetime.now()
  if due<=created:return now>=due
  return (now-created).total_seconds()/(due-created).total_seconds()*100>=percent
 except Exception:return False

def daily_service_maintenance():
 """Refresh existing SLA state, issue warnings/escalations and notify requester/approver targets."""
 if not registry.exists("Request"):return {"scanned":0,"updated":0,"warnings":0,"breaches":0}
 rows=get_list("Request",filters={"status":"Pending Approval","docstatus":1},fields=["name","sla_due_datetime","sla_status","escalated","creation","service","request_type","sla_paused"],limit=10000,ignore_permissions=True)
 now=datetime.now();updated=warnings=breaches=0
 for row in rows:
  try:
   doc=get_doc("Request",row["name"],ignore_permissions=True);due=getattr(doc,"sla_due_datetime",None)
   if not due or getattr(doc,"sla_paused",0):continue
   due_dt=datetime.fromisoformat(str(due));state="Overdue" if due_dt<now else "Due Soon" if (due_dt-now).total_seconds()<=24*3600 else "On Track"
   changed=state!=getattr(doc,"sla_status",None);doc.sla_status=state
   warning_percent=80
   if getattr(doc,"service",None):
    try:warning_percent=int(getattr(get_doc("Service",doc.service,ignore_permissions=True),"sla_warning_percent",80) or 80)
    except Exception:pass
   if due_warning(doc,warning_percent) and not getattr(doc,"sla_warning_sent",0):
    notify_requester(doc,"Request SLA warning",f"Request {doc.name} is approaching its approval SLA deadline.");doc.sla_warning_sent=1;warnings+=1;changed=True
   if state=="Overdue" and not getattr(doc,"escalated",0):
    doc.escalated=1;doc.escalated_on=now.strftime("%Y-%m-%d %H:%M:%S");breaches+=1;changed=True
    notify_requester(doc,"Request SLA breached",f"Request {doc.name} has breached its approval SLA.")
   if changed:doc.save(ignore_permissions=True);updated+=1
  except Exception:continue
 return {"scanned":len(rows),"updated":updated,"warnings":warnings,"breaches":breaches}


def operations_dashboard():
 _admin()
 from .service_catalog import dashboard
 result=dashboard()
 requests=get_list("Request",fields=["name","status","sla_status","creation","sla_due_datetime","current_level","department","service","request_type","reopened_count"],limit=10000,ignore_permissions=True)
 result["approval_statuses"]={};result["sla_statuses"]={};result["approval_bottlenecks"]={};result["request_trends"]={};result["reopened_requests"]=0
 for r in requests:
  status=r.get("status") or "Unknown";result["approval_statuses"][status]=result["approval_statuses"].get(status,0)+1
  sla=r.get("sla_status") or "Unknown";result["sla_statuses"][sla]=result["sla_statuses"].get(sla,0)+1
  if int(r.get("reopened_count") or 0)>0:result["reopened_requests"]+=1
  if status=="Pending Approval":
   level=str(r.get("current_level") or "0");result["approval_bottlenecks"][level]=result["approval_bottlenecks"].get(level,0)+1
   month=str(r.get("creation") or "")[:7];result["request_trends"][month]=result["request_trends"].get(month,0)+1
 try:
  feedback=get_list("Service Feedback",fields=["service","rating","service_quality_flag","submitted_on"],limit=10000,ignore_permissions=True)
  ratings=[];by_service={};flags={}
  for f in feedback:
   rating=int(f.get("rating") or 0)
   if rating>0:ratings.append(rating)
   svc=f.get("service") or "Unspecified";agg=by_service.setdefault(svc,{"count":0,"total_rating":0,"average_rating":0})
   agg["count"]+=1;agg["total_rating"]+=rating;agg["average_rating"]=round(agg["total_rating"]/agg["count"],2)
   flag=f.get("service_quality_flag") or "Neutral";flags[flag]=flags.get(flag,0)+1
  result["service_quality"]={"feedback_count":len(feedback),"average_rating":round(sum(ratings)/len(ratings),2) if ratings else None,"rating_distribution":{str(i):ratings.count(i) for i in range(1,6)},"quality_flags":flags,"ratings_by_service":by_service}
 except Exception:result["service_quality"]={"feedback_count":0,"average_rating":None,"ratings_by_service":{}}
 return result


def pause_request_sla(name, reason):
 """Administrative pause with required reason and auditable timestamps."""
 _admin();doc=get_doc("Request",name,ignore_permissions=True)
 if doc.status!="Pending Approval":raise ValueError("Only requests pending approval can have their SLA paused.")
 if getattr(doc,"sla_paused",0):return {"name":name,"sla_paused":True,"already_paused":True}
 if doc.service:
  service=get_doc("Service",doc.service,ignore_permissions=True)
  if not getattr(service,"sla_pause_allowed",1):raise ValueError("This service does not permit SLA pauses.")
  if getattr(service,"sla_pause_reason_required",1) and not str(reason or "").strip():raise ValueError("A pause reason is required for this service.")
 elif not str(reason or "").strip():raise ValueError("A pause reason is required.")
 doc.sla_paused=1;doc.sla_paused_on=datetime.now().isoformat(timespec="seconds");doc.sla_pause_reason=str(reason or "")
 doc.save(ignore_permissions=True)
 return {"name":name,"sla_paused":True,"sla_paused_on":doc.sla_paused_on}

def resume_request_sla(name):
 """Resume SLA and shift the existing due date by the paused duration."""
 _admin();doc=get_doc("Request",name,ignore_permissions=True)
 if not getattr(doc,"sla_paused",0):return {"name":name,"sla_paused":False,"already_resumed":True}
 paused=datetime.fromisoformat(str(doc.sla_paused_on));now=datetime.now();duration=max((now-paused).total_seconds()/3600,0)
 due=getattr(doc,"sla_due_datetime",None)
 if due:doc.sla_due_datetime=(datetime.fromisoformat(str(due))+timedelta(hours=duration)).isoformat(timespec="seconds")
 doc.sla_pause_duration_hours=float(getattr(doc,"sla_pause_duration_hours",0) or 0)+duration
 doc.sla_paused=0;doc.sla_paused_on=None;doc.sla_pause_reason=None
 doc.save(ignore_permissions=True)
 return {"name":name,"sla_paused":False,"pause_duration_hours":round(duration,2),"sla_due_datetime":doc.sla_due_datetime}
