"""Velora Admin approval-centre API routes."""
from fastapi import Body, FastAPI, Request

from .approval_service import (approve, reject, inbox, summary, routing_diagnostics, my_requests, request_detail, request_catalog, create_request, submit_request, delegation_list, delegation_create, delegation_update, escalation_rules, escalation_rule_create, escalation_rule_update, analytics)


def install_routes(app: FastAPI, scope, run):

    from .renewal_management import renewal_dashboard

    @app.get("/api/admin/renewals/dashboard")
    def renewal_dashboard_endpoint(request: Request):
        return run(request, renewal_dashboard)

    @app.get("/api/admin/requests/catalog")
    def admin_request_catalog(request: Request):
        return run(request, request_catalog)

    @app.post("/api/admin/requests")
    def admin_create_request(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: create_request(body or {}))

    @app.post("/api/admin/requests/{name}/submit")
    def admin_submit_request(name: str, request: Request):
        return run(request, lambda: submit_request(name))

    @app.get("/api/admin/requests/my")
    def admin_my_requests(request: Request):
        return run(request, my_requests)

    @app.get("/api/admin/requests/{name}")
    def admin_request_detail(name: str, request: Request):
        return run(request, lambda: request_detail(name))

    @app.get("/api/admin/approvals/inbox")
    def approval_inbox(request: Request):
        return run(request, inbox)

    @app.get("/api/admin/approvals/summary")
    def approval_summary(request: Request):
        return run(request, summary)

    @app.post("/api/admin/requests/{name}/approve")
    def approve_request(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: approve(name, (body or {}).get("comment", "")))

    @app.post("/api/admin/requests/{name}/reject")
    def reject_request(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: reject(name, (body or {}).get("comment", "")))

    @app.get("/api/admin/requests/{name}/routing-diagnostics")
    def routing_diagnostics_request(name: str, request: Request):
        return run(request, lambda: routing_diagnostics(name))


    @app.get("/api/admin/analytics")
    def admin_analytics(request: Request):
        return run(request, analytics)

    @app.get("/api/admin/delegations")
    def admin_delegations(request: Request):
        return run(request, delegation_list)

    @app.post("/api/admin/delegations")
    def admin_delegation_create(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: delegation_create(body or {}))

    @app.put("/api/admin/delegations/{name}")
    def admin_delegation_update(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: delegation_update(name, body or {}))

    @app.get("/api/admin/escalation-rules")
    def admin_escalation_rules(request: Request):
        return run(request, escalation_rules)

    @app.post("/api/admin/escalation-rules")
    def admin_escalation_rule_create(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: escalation_rule_create(body or {}))

    @app.put("/api/admin/escalation-rules/{name}")
    def admin_escalation_rule_update(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: escalation_rule_update(name, body or {}))

    from . import fulfilment_service
    from . import service_catalog

    @app.get("/api/admin/services/catalog")
    def admin_service_catalog(request: Request):
        return run(request, service_catalog.catalog)

    @app.get("/api/admin/services/{name}")
    def admin_service_detail(name: str, request: Request):
        return run(request, lambda: service_catalog.service_detail(name))

    @app.post("/api/admin/services")
    def admin_service_create(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_catalog.service_create(body or {}))

    @app.put("/api/admin/services/{name}")
    def admin_service_update(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_catalog.service_update(name, body or {}))

    @app.get("/api/admin/fulfilment-templates")
    def admin_template_list(request: Request, service: str = None):
        return run(request, lambda: service_catalog.templates(service))

    @app.post("/api/admin/fulfilment-templates")
    def admin_template_create(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_catalog.template_create(body or {}))

    @app.put("/api/admin/fulfilment-templates/{name}")
    def admin_template_update(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_catalog.template_update(name, body or {}))

    from . import service_operations, service_portal, universal_admin, operations_ui

    @app.get("/api/admin/universal/ui")
    def universal_admin_operations_ui(request: Request):
        from fastapi.responses import HTMLResponse
        return HTMLResponse(operations_ui.operations_center_html())


    # Universal Administration operations (v1.5.0). These endpoints provide
    # operational records and configurable automation; approval workflow remains
    # delegated to the existing framework workflow engine.
    @app.post("/api/admin/universal/tasks/{name}/complete")
    def universal_task_complete(request: Request, name: str, body: dict = Body(default={} )):
        return run(request, lambda: universal_admin.complete_task(name, (body or {}).get("notes")))

    @app.post("/api/admin/universal/work-orders")
    def universal_work_order_create(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: universal_admin.create_work_order(body or {}))

    @app.post("/api/admin/universal/work-orders/{name}/complete")
    def universal_work_order_complete(request: Request, name: str, body: dict = Body(default={} )):
        payload=body or {}
        return run(request, lambda: universal_admin.complete_work_order(name, payload.get("actual_cost"), payload.get("notes")))

    @app.get("/api/admin/universal/fleet/alerts")
    def universal_vehicle_alerts(request: Request, days_ahead: int = 30):
        return run(request, lambda: universal_admin.vehicle_alerts(days_ahead))

    @app.post("/api/admin/universal/supplies/transactions")
    def universal_stock_transaction(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: universal_admin.process_stock_transaction(body or {}))

    @app.post("/api/admin/universal/fleet/trip-conflicts")
    def universal_trip_conflicts(request: Request, body: dict = Body(default={} )):
        payload=body or {}
        return run(request, lambda: universal_admin.check_vehicle_trip_conflicts(payload.get("vehicle"), payload.get("driver"), payload.get("departure"), payload.get("returning"), payload.get("exclude_name")))

    @app.post("/api/admin/universal/events/venue-conflicts")
    def universal_event_conflicts(request: Request, body: dict = Body(default={} )):
        payload=body or {}
        return run(request, lambda: universal_admin.check_facility_booking_conflicts(payload.get("venue"), payload.get("start"), payload.get("end"), payload.get("exclude_name")))

    @app.post("/api/admin/universal/automation/run-daily")
    def universal_daily_automation(request: Request):
        return run(request, universal_admin.run_daily_admin_automation)

    @app.get("/api/admin/universal/operations-dashboard")
    def universal_admin_dashboard(request: Request):
        return run(request, universal_admin.operations_dashboard)

    @app.post("/api/admin/universal/tasks")
    def universal_admin_create_task(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: universal_admin.create_task(body or {}))

    @app.get("/api/admin/universal/records/{domain}")
    def universal_admin_records(request: Request, domain: str, limit: int = 100):
        return run(request, lambda: universal_admin.list_records(domain, limit=limit))

    @app.get("/api/admin/universal/knowledge/search")
    def universal_admin_knowledge_search(request: Request, q: str = "", category: str = None, limit: int = 30):
        return run(request, lambda: universal_admin.knowledge_search(q, category, limit))

    @app.post("/api/admin/universal/automation/evaluate")
    def universal_admin_automation_evaluate(request: Request, body: dict = Body(default={} )):
        payload = body or {}
        return run(request, lambda: universal_admin.evaluate_rules(payload.get("event", ""), payload.get("record", {}), True))

    @app.post("/api/admin/requests/{name}/sla/pause")
    def admin_pause_request_sla(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_operations.pause_request_sla(name, (body or {}).get("reason", "")))

    @app.post("/api/admin/requests/{name}/sla/resume")
    def admin_resume_request_sla(name: str, request: Request):
        return run(request, lambda: service_operations.resume_request_sla(name))

    @app.get("/api/admin/service-operations/operations-centre")
    def admin_operations_centre(request: Request):
        return run(request, service_operations.operations_dashboard)

    @app.get("/api/admin/service-portal/catalog")
    def employee_service_catalog(request: Request):
        return run(request, service_portal.catalog)

    @app.get("/api/admin/service-portal/services/{name}")
    def employee_service_detail(name: str, request: Request):
        return run(request, lambda: service_portal.service_detail(name))

    @app.post("/api/admin/service-portal/requests")
    def employee_service_request(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_portal.create_service_request(body or {}))

    @app.get("/api/admin/service-portal/requests/my")
    def employee_my_requests(request: Request):
        return run(request, service_portal.my_requests)

    @app.get("/api/admin/service-portal/requests/{name}/progress")
    def employee_request_progress(name: str, request: Request):
        return run(request, lambda: service_portal.request_progress(name))

    @app.post("/api/admin/service-portal/requests/{name}/comments")
    def employee_request_comment(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_portal.add_request_comment(name, body or {}))

    @app.post("/api/admin/service-portal/requests/{name}/cancel")
    def employee_cancel_request(name: str, request: Request):
        return run(request, lambda: service_portal.cancel_request(name))

    @app.get("/api/admin/service-operations/dashboard")
    def admin_service_operations_dashboard(request: Request):
        return run(request, service_operations.operations_dashboard)

    @app.get("/api/admin/service-operations/workbench")
    def admin_service_workbench(request: Request):
        def workbench():
            return {"catalog": service_catalog.catalog(), "templates": service_catalog.templates(), "operations": service_operations.operations_dashboard(), "governance_due": service_catalog.service_governance_review_due()}
        return run(request, workbench)

    @app.get("/api/admin/services/{name}/governance")
    def admin_service_governance(name: str, request: Request):
        return run(request, lambda: service_catalog.service_governance(name))

    @app.put("/api/admin/services/{name}/governance")
    def admin_service_governance_update(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_catalog.service_governance(name, body or {}))

    @app.get("/api/admin/service-operations/governance-review-due")
    def admin_governance_review_due(request: Request):
        return run(request, service_catalog.service_governance_review_due)

    @app.post("/api/admin/services/{name}/governance/review")
    def admin_service_mark_reviewed(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_catalog.mark_service_reviewed(name, (body or {}).get("notes")))

    @app.get("/api/admin/service-portal/search")
    def employee_service_search(request: Request, q: str = "", category: str = None):
        return run(request, lambda: service_portal.portal_search(q, category))

    @app.get("/api/admin/service-portal/ui")
    def employee_service_portal_ui(request: Request):
        from fastapi.responses import HTMLResponse
        html = service_portal.portal_html()
        return HTMLResponse(html)

    @app.get("/api/admin/service-portal/requests/{name}/timeline")
    def employee_request_timeline(name: str, request: Request):
        return run(request, lambda: service_portal.request_timeline(name))

    @app.post("/api/admin/service-portal/requests/{name}/feedback")
    def employee_request_feedback(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_portal.request_feedback(name, body or {}))

    @app.post("/api/admin/service-portal/requests/{name}/staff-comments")
    def admin_staff_comment(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: service_portal.staff_comment(name, body or {}))

    @app.get("/api/admin/fulfilment/approved-queue")
    def admin_fulfilment_approved_queue(request: Request):
        return run(request, fulfilment_service.approved_queue)

    @app.post("/api/admin/fulfilment/from-request/{request_name}")
    def admin_fulfilment_from_request(request_name: str, request: Request):
        return run(request, lambda: fulfilment_service.create_from_approved_request(request_name))

    @app.get("/api/admin/fulfilment")
    def admin_fulfilment_list(request: Request):
        return run(request, fulfilment_service.list_fulfilment)

    @app.get("/api/admin/fulfilment/{name}")
    def admin_fulfilment_detail(name: str, request: Request):
        return run(request, lambda: fulfilment_service.get_fulfilment(name))

    @app.get("/api/admin/fulfilment/routing-recommendation/{request_name}")
    def admin_fulfilment_routing_recommendation(request_name: str, request: Request):
        return run(request, lambda: fulfilment_service.routing_recommendation(request_name))

    @app.post("/api/admin/fulfilment/{name}/assign")
    def admin_fulfilment_assign(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: fulfilment_service.assign_fulfilment(name, body or {}))

    @app.post("/api/admin/fulfilment/{name}/start")
    def admin_fulfilment_start(name: str, request: Request):
        return run(request, lambda: fulfilment_service.start_fulfilment(name))

    @app.post("/api/admin/fulfilment/{name}/tasks")
    def admin_fulfilment_add_task(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: fulfilment_service.add_task(name, body or {}))

    @app.put("/api/admin/fulfilment/{name}/tasks/{task_id}")
    def admin_fulfilment_update_task(name: str, task_id: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: fulfilment_service.update_task(name, task_id, body or {}))

    @app.post("/api/admin/fulfilment/{name}/complete")
    def admin_fulfilment_complete(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: fulfilment_service.complete_fulfilment(name, body or {}))

    @app.post("/api/admin/fulfilment/{name}/close")
    def admin_fulfilment_close(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: fulfilment_service.close_fulfilment(name, (body or {}).get("reason", "")))

    @app.post("/api/admin/fulfilment/{name}/reopen")
    def admin_fulfilment_reopen(name: str, request: Request, body: dict = Body(default={} )):
        return run(request, lambda: fulfilment_service.reopen_fulfilment(name, (body or {}).get("reason", "")))
