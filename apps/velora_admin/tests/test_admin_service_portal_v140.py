import json
from pathlib import Path
from fastapi import FastAPI
from velora_admin.api_routes import install_routes

ROOT=Path(__file__).resolve().parents[1]
DOCTYPE=ROOT/'velora_admin'/'administration'/'doctype'

def test_v140_feedback_doctype_native_and_unique_request():
 data=json.loads((DOCTYPE/'service_feedback'/'service_feedback.json').read_text())
 assert data['name']=='Service Feedback'
 assert 'Velora' not in data['name']
 fields={f['fieldname']:f for f in data['fields']}
 assert fields['request']['unique'] is True
 assert {'rating','feedback','service_quality_flag','submitted_on'}.issubset(fields)

def test_service_governance_fields_added_to_existing_service_doctype():
 data=json.loads((DOCTYPE/'service'/'service.json').read_text())
 fields={f['fieldname']:f for f in data['fields']}
 assert {'service_owner','service_status','review_frequency_months','last_reviewed_on','next_review_date','governance_notes','quality_rating_enabled'}.issubset(fields)
 assert fields['service_status']['options'].splitlines()==['Draft','Active','Under Review','Suspended','Retired']

def test_v140_portal_collaboration_governance_routes_register():
 app=FastAPI();install_routes(app,None,lambda request,fn: fn())
 paths={r.path for r in app.routes}
 expected={
  '/api/admin/service-portal/ui','/api/admin/service-portal/search','/api/admin/service-portal/services/{name}',
  '/api/admin/service-portal/requests/{name}/timeline','/api/admin/service-portal/requests/{name}/feedback',
  '/api/admin/service-portal/requests/{name}/staff-comments','/api/admin/services/{name}/governance',
  '/api/admin/services/{name}/governance/review','/api/admin/service-operations/workbench',
  '/api/admin/service-operations/governance-review-due'
 }
 assert expected.issubset(paths)

def test_portal_html_has_catalog_dynamic_forms_my_requests_and_feedback():
 from velora_admin.administration.service_portal import portal_html
 html=portal_html()
 for marker in ('Service Catalogue','My Requests','requestForm','feedbackForm','timeline','form_data','Submit Request'):
  assert marker in html

def test_v140_reopen_and_routing_recommendation_routes_register():
 app=FastAPI();install_routes(app,None,lambda request,fn: fn())
 paths={r.path for r in app.routes}
 assert '/api/admin/fulfilment/{name}/reopen' in paths
 assert '/api/admin/fulfilment/routing-recommendation/{request_name}' in paths

def test_request_and_existing_fulfilment_reopen_tracking_fields():
 req=json.loads((DOCTYPE/'request'/'request.json').read_text())
 rf={f['fieldname'] for f in req['fields']}
 assert {'reopened_count','last_reopened_on','reopening_reason'}.issubset(rf)
 assignment=json.loads((DOCTYPE/'request_fulfilment'/'request_fulfilment.json').read_text())
 af={f['fieldname'] for f in assignment['fields']}
 assert {'reopen_count','last_reopened_on','reopening_reason'}.issubset(af)

def test_routing_recommendation_is_capacity_ranked_and_advisory(monkeypatch):
 from velora_admin.administration import fulfilment_service as fs
 class Req:
  service='Service-X';priority='High'
 class Service: default_team='Team-A';name='Service-X'
 monkeypatch.setattr(fs,'_session',lambda:object())
 monkeypatch.setattr(fs,'_is_admin',lambda s:True)
 monkeypatch.setattr(fs,'get_doc',lambda doctype,name,ignore_permissions=True: Req() if doctype=='Request' else Service())
 monkeypatch.setattr(fs,'get_list',lambda *a,**k:[{'assigned_team':'Team-A','status':'In Progress'},{'assigned_team':'Team-A','status':'Assigned'},{'assigned_team':'Team-B','status':'In Progress'}])
 result=fs.routing_recommendation('REQ-1')
 assert result['recommended_team']=='Team-B'
 assert result['is_suggestion_only'] is True
 assert result['priority']=='High'
