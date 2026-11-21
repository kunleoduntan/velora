"""Provider-neutral attendance ingestion and ZKTeco BioTime report connector.

Provider secrets are read from environment variables, never stored in DocTypes.
All external attendance remains pending HR approval until reviewed.
"""
from __future__ import annotations
import hashlib, json, os, ssl
from datetime import datetime, date, timezone, timedelta
from urllib.parse import urlparse, urlencode
from zoneinfo import ZoneInfo
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError, VeloraError
from velora import safe_http

PROVIDERS = {
    "ZKTeco BioTime": {"mode":"REST API Pull", "status":"Native REST report connector"},
    "ZKTeco ADMS Gateway": {"mode":"Normalised Event Push", "status":"Gateway adapter; vendor protocol runs at edge"},
    "eSSL": {"mode":"Normalised Event Push", "status":"Provider gateway / normalised event adapter"},
    "Hikvision": {"mode":"Normalised Event Push", "status":"Provider gateway / normalised event adapter"},
    "Suprema": {"mode":"Normalised Event Push", "status":"Provider gateway / normalised event adapter"},
    "Anviz": {"mode":"Normalised Event Push", "status":"Provider gateway / normalised event adapter"},
    "Matrix": {"mode":"Normalised Event Push", "status":"Provider gateway / normalised event adapter"},
    "Dahua": {"mode":"Normalised Event Push", "status":"Provider gateway / normalised event adapter"},
    "Generic REST API": {"mode":"Normalised Event Push", "status":"Configurable integration contract"},
    "CSV Import": {"mode":"CSV Import", "status":"Normalised CSV import contract"},
    "SFTP Gateway": {"mode":"SFTP Staging", "status":"Staged-file connector contract"},
}

def _dt(value, tz="Africa/Lagos"):
    if isinstance(value, datetime): d=value
    else:
        raw=str(value or "").strip()
        if not raw: raise ValidationError("Punch timestamp is required.")
        try: d=datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError: 
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try: d=datetime.strptime(raw,fmt); break
                except ValueError: d=None
            if d is None: raise ValidationError(f"Unsupported punch timestamp: {raw[:60]}")
    zone=ZoneInfo(tz or "UTC")
    if d.tzinfo is None: d=d.replace(tzinfo=zone)
    return d.astimezone(zone).replace(tzinfo=None)

def _key(integration, serial, user, occurred, source_id=None, state=None):
    # Prefer a provider event ID so retries remain idempotent even if a vendor
    # corrects a timestamp or verification field on a previously delivered event.
    parts=(integration,serial,"provider-event",source_id) if source_id else (integration,serial,user,occurred,state)
    return hashlib.sha256("|".join(str(x or "") for x in parts).encode()).hexdigest()

def _device_for(integration, serial):
    rows=get_list("Attendance Device",filters=[["integration","=",integration],["serial_number","=",serial],["active","=",1]],fields=["name","timezone"],limit=2,ignore_permissions=True)
    return rows[0] if rows else None

def _map_employee(integration, device, external_user_id, occurred):
    filters=[["integration","=",integration],["external_user_id","=",str(external_user_id)],["active","=",1]]
    rows=get_list("Attendance Device User Mapping",filters=filters,fields=["name","device","employee","effective_from","effective_to"],limit=100,ignore_permissions=True)
    d=occurred.date()
    for row in rows:
        if row.get("device") and row.get("device")!=device: continue
        start=date.fromisoformat(str(row["effective_from"])[:10]) if row.get("effective_from") else date.min
        end=date.fromisoformat(str(row["effective_to"])[:10]) if row.get("effective_to") else date.max
        if start<=d<=end: return row.get("employee")
    return None

def ingest_events(integration_name, events, source="Normalised Event Push"):
    integration=get_doc("Attendance Integration",integration_name,ignore_permissions=True)
    if not integration.active: raise ValidationError("Attendance integration is inactive.")
    if not isinstance(events,list) or not events or len(events)>500: raise ValidationError("Provide between 1 and 500 attendance events per request.")
    created=duplicate=unmapped=0; errors=[]
    for index,event in enumerate(events):
        try:
            if not isinstance(event,dict): raise ValidationError("Each event must be an object.")
            serial=str(event.get("serial_number") or event.get("device_serial") or "").strip()
            external_user=str(event.get("external_user_id") or event.get("user_id") or event.get("emp_code") or "").strip()
            if not external_user: raise ValidationError("External user identifier is missing.")
            device=_device_for(integration_name,serial) if serial else None
            tz_name=(device or {}).get("timezone") or integration.timezone or "UTC"
            occurred=_dt(event.get("punch_datetime") or event.get("timestamp") or event.get("occurred_at"),tz_name)
            event_id=str(event.get("event_id") or event.get("id") or "")
            key=_key(integration_name,serial,external_user,occurred.isoformat(),event_id,event.get("punch_state"))
            exists=get_list("External Attendance Punch",filters=[["external_event_key","=",key]],fields=["name"],limit=1,ignore_permissions=True)
            if exists: duplicate+=1; continue
            employee=_map_employee(integration_name,(device or {}).get("name"),external_user,occurred)
            doc=new_doc("External Attendance Punch",external_event_key=key,integration=integration_name,
                device=(device or {}).get("name"),serial_number=serial,external_user_id=external_user,employee=employee,
                punch_datetime=occurred.isoformat(timespec="seconds"),punch_state=str(event.get("punch_state") or ""),
                verify_type=str(event.get("verify_type") or ""),source_event_id=event_id,
                processing_status="Ready" if employee else "Unmapped",raw_payload=event,
                received_on=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            doc.insert(ignore_permissions=True); created+=1
            if device:
                try:
                    device_doc=get_doc("Attendance Device",device,ignore_permissions=True)
                    device_doc.last_seen_on=datetime.now(timezone.utc).isoformat(timespec="seconds")
                    device_doc.last_event_on=occurred.isoformat(timespec="seconds")
                    device_doc.health_status="Online"
                    device_doc.last_sync_status="Connected"
                    device_doc.save(ignore_permissions=True)
                except Exception:
                    pass
            if not employee: unmapped+=1
        except Exception as exc:
            errors.append({"row":index+1,"error":str(exc)[:250]})
    return {"received":len(events),"created":created,"duplicates":duplicate,"unmapped":unmapped,"errors":errors}

def _shift_work_date(employee, occurred, cache=None):
    """Resolve a punch to an approved shift work date, including overnight shifts.

    Falls back to the local calendar date when no applicable approved shift exists.
    A four-hour boundary tolerance accommodates early clock-ins and late clock-outs.
    """
    cache = cache if cache is not None else {}
    if ("a", employee) not in cache:       # one lookup per employee, not one per punch
        cache[("a", employee)] = get_list("Shift Assignment",filters=[["employee","=",employee],["assignment_status","=","Approved"]],
            fields=["name","shift_type","effective_from","effective_to","days_of_week"],limit=100,ignore_permissions=True)
    assignments = cache[("a", employee)]
    for candidate in (occurred.date(), (occurred.date()).fromordinal(occurred.date().toordinal()-1)):
        for assignment in assignments:
            start=date.fromisoformat(str(assignment.get("effective_from"))[:10]) if assignment.get("effective_from") else date.min
            finish=date.fromisoformat(str(assignment.get("effective_to"))[:10]) if assignment.get("effective_to") else date.max
            if not start<=candidate<=finish: continue
            days=assignment.get("days_of_week") or []
            if isinstance(days,str):
                try: days=json.loads(days)
                except Exception: days=[]
            weekday=candidate.strftime("%A")
            if days and weekday not in days: continue
            try:
                if ("s", assignment["shift_type"]) not in cache: cache[("s", assignment["shift_type"])] = get_doc("Shift Type",assignment["shift_type"],ignore_permissions=True)
                shift = cache[("s", assignment["shift_type"])]
            except Exception: continue
            try:
                from datetime import time, timedelta
                st=time.fromisoformat(str(shift.start_time)); et=time.fromisoformat(str(shift.end_time))
                begins=datetime.combine(candidate,st)-timedelta(hours=4)
                ends=datetime.combine(candidate,et)
                if getattr(shift,"crosses_midnight",False) or et<=st: ends+=timedelta(days=1)
                ends+=timedelta(hours=4)
                if begins<=occurred<=ends: return candidate
            except Exception:
                continue
    return occurred.date()

def reconcile_punches(integration_name, start_date=None, end_date=None, limit=2000):
    filters=[["integration","=",integration_name],["processing_status","=","Ready"]]
    # Include adjacent calendar dates so overnight shift punches can be grouped
    # against the shift's start date without losing the post-midnight clock-out.
    if start_date: filters.append(["punch_datetime",">=",str(date.fromisoformat(str(start_date))-timedelta(days=1))+" 00:00:00"])
    if end_date: filters.append(["punch_datetime","<=",str(date.fromisoformat(str(end_date))+timedelta(days=1))+" 23:59:59"])
    punches=get_list("External Attendance Punch",filters=filters,fields=["name","employee","punch_datetime","device","external_user_id"],order_by="punch_datetime asc",limit=min(max(int(limit),1),5000),ignore_permissions=True)
    groups={}
    _shift_cache={}
    for row in punches:
        occurred=datetime.fromisoformat(str(row["punch_datetime"]).replace("Z",""))
        work_date=_shift_work_date(row["employee"],occurred,_shift_cache)
        groups.setdefault((row["employee"],work_date),[]).append((row,occurred))
    created=conflicts=needs_review=0; details=[]
    for (employee,day),items in groups.items():
        items.sort(key=lambda x:x[1]); first,last=items[0][1],items[-1][1]
        if len(items)<2 or first==last:
            for row,_ in items:
                doc=get_doc("External Attendance Punch",row["name"],ignore_permissions=True); doc.processing_status="Needs Review"; doc.processing_notes="Only one unique punch is available for this employee/shift; HR must review before attendance can be generated."; doc.save(ignore_permissions=True)
            needs_review+=1; continue
        existing=get_list("Attendance",filters=[["employee","=",employee],["attendance_date","=",day.isoformat()]],fields=["name"],limit=2,ignore_permissions=True)
        if existing:
            for row,_ in items:
                doc=get_doc("External Attendance Punch",row["name"],ignore_permissions=True); doc.processing_status="Conflict"; doc.processing_notes=f"An Attendance record already exists for this employee/work date ({existing[0]['name']}); no overwrite performed."; doc.save(ignore_permissions=True)
            conflicts+=1; continue
        attendance=new_doc("Attendance",employee=employee,attendance_date=day.isoformat(),status="Present",
            check_in=first.isoformat(timespec="seconds"),check_out=last.isoformat(timespec="seconds"),
            attendance_source="Integration",device_reference=integration_name,approval_status="Pending Approval",
            remarks=f"Generated from {len(items)} imported device punches; shift-aware work date; pending HR review.")
        try:
            attendance.insert(ignore_permissions=True)
        except VeloraError as exc:       # e.g. the employee is on approved leave that day: park the punches for HR, keep going
            for row,_ in items:
                doc=get_doc("External Attendance Punch",row["name"],ignore_permissions=True); doc.processing_status="Needs Review"; doc.processing_notes=f"Attendance could not be created: {str(exc)[:200]}"; doc.save(ignore_permissions=True)
            needs_review+=1; continue
        for row,_ in items:
            doc=get_doc("External Attendance Punch",row["name"],ignore_permissions=True); doc.processing_status="Processed"; doc.attendance=attendance.name; doc.save(ignore_permissions=True)
        created+=1; details.append({"employee":employee,"date":day.isoformat(),"attendance":attendance.name,"punch_count":len(items)})
    return {"groups":len(groups),"attendance_created":created,"conflicts":conflicts,"needs_review":needs_review,"details":details}

def _https_json(url, token, params):
    parsed=urlparse(url)
    if parsed.scheme!="https" or not parsed.hostname: raise ValidationError("BioTime API must use HTTPS.")
    port=parsed.port or 443
    try: addresses=safe_http.resolve(parsed.hostname,port)
    except safe_http.UnsafeTarget as exc: raise ValidationError(f"Unsafe BioTime API host: {exc}") from None
    path=(parsed.path.rstrip("/") or "")+"/"+"?"+urlencode(params)
    conn=safe_http.PinnedHTTPSConnection(parsed.hostname,port,pinned_ip=addresses[0],timeout=20,context=ssl.create_default_context())
    try:
        conn.request("GET",path,headers={"Authorization":"JWT "+token,"Accept":"application/json"})
        response=conn.getresponse(); payload=response.read(3_000_001)
        if response.status<200 or response.status>=300: raise ValidationError(f"BioTime API returned HTTP {response.status}.")
        if len(payload)>3_000_000: raise ValidationError("BioTime response exceeded the 3 MB safety limit.")
        try: return json.loads(payload.decode("utf-8"))
        except Exception: raise ValidationError("BioTime API returned invalid JSON.") from None
    finally: conn.close()

def sync_biotime_report(integration_name, start_date, end_date):
    integration=get_doc("Attendance Integration",integration_name,ignore_permissions=True)
    if integration.provider!="ZKTeco BioTime" or integration.transport!="REST API Pull": raise ValidationError("This integration is not configured as a ZKTeco BioTime REST connector.")
    if not integration.active: raise ValidationError("Attendance integration is inactive.")
    start=date.fromisoformat(str(start_date)); end=date.fromisoformat(str(end_date))
    if end<start or (end-start).days>31: raise ValidationError("Select a valid date range of no more than 31 days per sync.")
    env_name=str(integration.credential_env or "").strip(); token=os.environ.get(env_name)
    if not token: raise ValidationError(f"The server environment variable {env_name} is not configured.")
    base=str(integration.api_base_url).rstrip("/"); endpoint=str(integration.attendance_endpoint or "/att/api/firstLastReport/")
    url=base+("" if endpoint.startswith("/") else "/")+endpoint
    page=1; page_size=min(max(int(integration.page_size or 100),1),500); fetched=created=skipped=unmapped=0; warnings=[]
    run=new_doc("Attendance Sync Run",integration=integration_name,provider=integration.provider,sync_mode="API Pull",period_start=start.isoformat(),period_end=end.isoformat(),run_status="Running",started_on=datetime.now(timezone.utc).isoformat(timespec="seconds")); run.insert(ignore_permissions=True)
    try:
        while page<=100:
            result=_https_json(url,token,{"page":page,"page_size":page_size,"start_date":start.isoformat(),"end_date":end.isoformat()})
            rows=result.get("data",[]) if isinstance(result,dict) else []
            if not isinstance(rows,list): raise ValidationError("BioTime response data must be an array.")
            fetched+=len(rows); normalised=[]; tz=ZoneInfo(integration.timezone or "UTC")
            for row in rows:
                external=str(row.get("emp_code") or "").strip(); day=str(row.get("att_date") or "")[:10]
                if not external or not day:
                    skipped+=1; warnings.append("A BioTime row lacked emp_code or att_date."); continue
                try:
                    d=date.fromisoformat(day)
                    first=datetime.combine(d,datetime.strptime(str(row.get("first_punch")),"%I:%M %p").time()).replace(tzinfo=tz) if row.get("first_punch") else None
                    last=datetime.combine(d,datetime.strptime(str(row.get("last_punch")),"%I:%M %p").time()).replace(tzinfo=tz) if row.get("last_punch") else None
                    if not first or not last or last<first:
                        skipped+=1; warnings.append(f"Invalid first/last punch for {external} on {day}."); continue
                    normalised.extend([
                        {"external_user_id":external,"timestamp":first.isoformat(),"event_id":f"biotime:{external}:{day}:first","punch_state":"IN","raw_payload":row},
                        {"external_user_id":external,"timestamp":last.isoformat(),"event_id":f"biotime:{external}:{day}:last","punch_state":"OUT","raw_payload":row},
                    ])
                except Exception as exc:
                    skipped+=1; warnings.append(f"{external}/{day}: {str(exc)[:160]}")
            if normalised:
                received=ingest_events(integration_name,normalised,source="ZKTeco BioTime REST API")
                skipped+=received["duplicates"]+len(received["errors"])
                unmapped+=received["unmapped"]
                warnings.extend(x.get("error","") for x in received["errors"])
            nxt=result.get("next") if isinstance(result,dict) else None
            if not rows or not nxt: break
            page+=1
        reconciled=reconcile_punches(integration_name,start.isoformat(),end.isoformat(),limit=5000)
        created=reconciled["attendance_created"]
        skipped+=reconciled["conflicts"]+reconciled["needs_review"]
        run.run_status="Completed With Warnings" if warnings or skipped or unmapped else "Completed"
        run.records_fetched=fetched; run.records_created=created; run.records_skipped=skipped; run.records_unmapped=unmapped; run.error_count=len(warnings)
        run.summary="; ".join(warnings[:20]) or "BioTime report synchronised into the punch inbox and reconciled to pending Attendance records."; run.finished_on=datetime.now(timezone.utc).isoformat(timespec="seconds"); run.save(ignore_permissions=True)
        integration.last_sync_on=run.finished_on; integration.last_successful_sync_on=run.finished_on
        integration.health_status="Healthy" if run.run_status=="Completed" else "Warning"
        integration.consecutive_failures=0; integration.last_health_check=run.finished_on
        integration.save(ignore_permissions=True)
        return {"sync_run":run.name,"fetched":fetched,"created":created,"skipped":skipped,"unmapped":unmapped,"warnings":warnings[:20]}
    except Exception as exc:
        run.run_status="Failed"; run.error_count=1; run.summary=str(exc)[:2000]; run.finished_on=datetime.now(timezone.utc).isoformat(timespec="seconds"); run.save(ignore_permissions=True)
        try:
            integration.health_status="Failed"; integration.last_health_check=run.finished_on
            integration.last_sync_on=run.finished_on
            integration.consecutive_failures=int(integration.consecutive_failures or 0)+1; integration.save(ignore_permissions=True)
        except Exception: pass
        raise


def test_biotime_connection(integration_name):
    """Perform a bounded, read-only connectivity/authentication test."""
    integration=get_doc("Attendance Integration",integration_name,ignore_permissions=True)
    if integration.provider!="ZKTeco BioTime" or integration.transport!="REST API Pull":
        raise ValidationError("Connection testing is currently available for ZKTeco BioTime REST integrations.")
    env_name=str(integration.credential_env or "").strip(); token=os.environ.get(env_name)
    if not token: raise ValidationError(f"The server environment variable {env_name} is not configured.")
    base=str(integration.api_base_url or "").rstrip("/"); endpoint=str(integration.attendance_endpoint or "/att/api/firstLastReport/")
    url=base+("" if endpoint.startswith("/") else "/")+endpoint
    result=_https_json(url,token,{"page":1,"page_size":1,"start_date":date.today().isoformat(),"end_date":date.today().isoformat()})
    if not isinstance(result,dict) or not isinstance(result.get("data",[]),list):
        raise ValidationError("BioTime returned an unexpected report response.")
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    integration.health_status="Healthy"; integration.last_health_check=now; integration.consecutive_failures=0; integration.save(ignore_permissions=True)
    return {"status":"Healthy","provider":integration.provider,"checked_on":now,"sample_rows":len(result.get("data",[]))}

def suggest_device_user_mappings(integration_name, limit=200):
    """Return exact employee-code matches for unmapped device identifiers; never auto-link."""
    punches=get_list("External Attendance Punch",filters=[["integration","=",integration_name],["processing_status","=","Unmapped"]],
        fields=["external_user_id","device","serial_number"],limit=min(max(int(limit),1),1000),ignore_permissions=True)
    seen=set(); suggestions=[]
    for punch in punches:
        ext=str(punch.get("external_user_id") or "").strip()
        if not ext or ext in seen: continue
        seen.add(ext)
        employees=get_list("Employee",filters=[["employee_code","=",ext]],fields=["name","employee_code","employee_name"],limit=2,ignore_permissions=True)
        suggestions.append({"external_user_id":ext,"device":punch.get("device"),"serial_number":punch.get("serial_number"),
            "suggested_employee":employees[0].get("name") if len(employees)==1 else None,
            "match_type":"Exact Employee Code" if len(employees)==1 else ("Ambiguous" if len(employees)>1 else "No Match"),
            "requires_hr_confirmation":True})
    return suggestions

def run_scheduled_attendance_syncs():
    """Hourly scheduler; executes only integrations explicitly opted into auto-sync."""
    from datetime import timedelta
    now=datetime.now(timezone.utc)
    integrations=get_list("Attendance Integration",filters=[["active","=",1],["auto_sync_enabled","=",1]],
        fields=["name","provider","sync_frequency","last_sync_on","lookback_days"],limit=500,ignore_permissions=True)
    outcomes=[]
    for row in integrations:
        if row.get("provider")!="ZKTeco BioTime": continue
        frequency=row.get("sync_frequency") or "Hourly"
        previous=datetime.fromisoformat(str(row["last_sync_on"]).replace("Z","+00:00")) if row.get("last_sync_on") else None
        interval={"Every 15 Minutes":timedelta(minutes=15),"Hourly":timedelta(hours=1),"Daily":timedelta(days=1)}.get(frequency,timedelta(hours=1))
        if previous and now-previous<interval: continue
        running=get_list("Attendance Sync Run",filters=[["integration","=",row["name"]],["run_status","=","Running"]],fields=["name"],limit=1,ignore_permissions=True)
        if running: continue
        days=min(max(int(row.get("lookback_days") or 2),1),31)
        end=now.date(); start=end-timedelta(days=days-1)
        try:
            result=sync_biotime_report(row["name"],start.isoformat(),end.isoformat())
            outcomes.append({"integration":row["name"],"status":"Completed","result":result})
        except Exception as exc:
            try:
                doc=get_doc("Attendance Integration",row["name"],ignore_permissions=True)
                doc.health_status="Failed"; doc.last_health_check=now.isoformat(timespec="seconds")
                doc.consecutive_failures=int(doc.consecutive_failures or 0)+1; doc.save(ignore_permissions=True)
            except Exception: pass
            outcomes.append({"integration":row["name"],"status":"Failed","error":str(exc)[:250]})
    return outcomes
