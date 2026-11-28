import json
from pathlib import Path
from fastapi import FastAPI
from velora_admin.api_routes import install_routes

ROOT=Path(__file__).resolve().parents[1]
DOCTYPE=ROOT/'velora_admin'/'administration'/'doctype'

UNIVERSAL_DOCTYPES=[
 'task','facility','facility_work_order','administrative_vehicle',
 'trip','vendor','supply_item','stock_transaction',
 'administrative_correspondence','administrative_event','administrative_visitor','administrative_travel_request',
 'automation_rule','knowledge_article'
]

def test_v150_universal_admin_doctypes_exist_and_no_velora_name_collision():
 for slug in UNIVERSAL_DOCTYPES:
  p=DOCTYPE/slug/(slug+'.json')
  assert p.exists(), slug
  data=json.loads(p.read_text())
  assert 'Velora' not in data['name']
  assert data['module']=='Administration'
  assert data['fields']


def test_admin_task_fields_cover_recurring_and_ownership():
 data=json.loads((DOCTYPE/'task'/'task.json').read_text())
 fields={f['fieldname'] for f in data['fields']}
 assert {'title','task_type','status','priority','assigned_to','due_date','recurrence','checklist_json'}.issubset(fields)


def test_facilities_fleet_and_supply_domains_have_operational_fields():
 checks={
  'facility':{'facility_type','parent_location','capacity','occupancy','facility_manager'},
  'facility_work_order':{'facility','work_type','status','scheduled_date','actual_cost','recurrence'},
  'administrative_vehicle':{'status','current_odometer','insurance_expiry','registration_expiry','service_due_date'},
  'trip':{'destination','departure_datetime','vehicle','driver','status'},
  'supply_item':{'quantity_on_hand','reorder_level','warehouse_location'},
 }
 for slug,required in checks.items():
  data=json.loads((DOCTYPE/slug/(slug+'.json')).read_text())
  fields={f['fieldname'] for f in data['fields']}
  assert required.issubset(fields),slug


def test_correspondence_event_visitor_travel_records_have_status_tracking():
 for slug in ('administrative_correspondence','administrative_event','administrative_visitor','administrative_travel_request'):
  data=json.loads((DOCTYPE/slug/(slug+'.json')).read_text())
  fields={f['fieldname'] for f in data['fields']}
  assert 'status' in fields


def test_automation_rules_are_configuration_driven_and_no_approval_workflow_hardcoded():
 data=json.loads((DOCTYPE/'automation_rule'/'automation_rule.json').read_text())
 fields={f['fieldname'] for f in data['fields']}
 assert {'trigger_event','scope_doctype','conditions_json','actions_json','priority','enabled'}.issubset(fields)
 assert not any('approval_level' in f or 'approver' in f for f in fields)


def test_v150_universal_admin_routes_register():
 app=FastAPI();install_routes(app,None,lambda request,fn:fn())
 paths={r.path for r in app.routes}
 assert {'/api/admin/universal/operations-dashboard','/api/admin/universal/tasks',
 '/api/admin/universal/records/{domain}','/api/admin/universal/knowledge/search',
 '/api/admin/universal/automation/evaluate'}.issubset(paths)
