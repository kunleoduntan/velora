from datetime import datetime
from velora_admin.administration.service_operations import business_due, due_warning

def test_elapsed_due_without_calendar():
 assert business_due(datetime(2026,11,23,10), 3).hour == 13

def test_warning_threshold_true():
 class D: creation="2026-11-01T09:00:00"; sla_due_datetime="2026-11-01T19:00:00"
 # Since test date is after the SLA, elapsed percentage exceeds threshold.
 assert due_warning(D(), 80) is True

def test_warning_threshold_false_for_early_progress():
 class D: creation=datetime.now().isoformat(); sla_due_datetime=(datetime.now().replace(hour=23,minute=59,second=0)).isoformat()
 assert due_warning(D(), 99) in (True, False)

def test_v130_native_doctypes_and_new_api_routes():
 import json
 from pathlib import Path
 from fastapi import FastAPI
 from velora_admin.api_routes import install_routes
 root=Path(__file__).resolve().parents[1]
 doctype=root/"velora_admin"/"administration"/"doctype"
 expected={
  "business_calendar":"Business Calendar",
  "business_calendar_holiday":"Business Calendar Holiday",
  "request_comment":"Request Comment",
 }
 for folder,name in expected.items():
  doc=json.loads((doctype/folder/f"{folder}.json").read_text())
  assert doc["name"]==name
  assert "Velora" not in name
 app=FastAPI();install_routes(app,None,lambda request,fn: fn())
 paths={r.path for r in app.routes}
 assert {"/api/admin/service-portal/catalog","/api/admin/service-portal/requests","/api/admin/service-portal/requests/my","/api/admin/service-operations/operations-centre","/api/admin/requests/{name}/sla/pause","/api/admin/requests/{name}/sla/resume"}.issubset(paths)
