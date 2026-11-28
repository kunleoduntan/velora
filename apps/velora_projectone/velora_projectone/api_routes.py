"""ProjectOne API route registration."""
def install_routes(app, scope, run):
    from fastapi import Body, Request
    from velora_projectone import velora_host
    run = velora_host.install(run)
    from velora_projectone.projectone.services.performance import calculate_earned_value
    from velora_projectone.projectone.services.risk import score_risk
    from velora_projectone.projectone.services.scheduling import calculate_schedule
    from velora_projectone.projectone.services.financial import calculate_budget_position
    from velora_projectone.projectone.services.lifecycle import validate_project, transition_project
    from velora_projectone.projectone.services.calendar import add_working_days, working_days_between
    from velora_projectone.projectone.services.resources import evaluate_resource_capacity, calculate_labour_cost
    from velora_projectone.projectone.services.project_finance import reconcile_commitment, calculate_project_financial_position, validate_source_reference
    from velora_projectone.projectone.reports.portfolio_summary import build_portfolio_summary
    from velora_projectone.projectone.services.schedule_dates import calculate_dated_schedule
    from velora_projectone.projectone.services.resource_planning import match_resource_skills, level_allocations
    from velora_projectone.projectone.services.commercial import cost_forecast, validate_contract, billing_position
    from velora_projectone.projectone.services.agile import (validate_sprint, sprint_metrics, validate_story, plan_sprint, kanban_board, burndown, sprint_review, validate_retrospective, transition_story)
    from velora_projectone.projectone.services.controls import assess_risk, validate_change_request, quality_gate
    from velora_projectone.projectone.reports.executive import executive_dashboard
    from velora_projectone.projectone.reports.dashboards import build_dashboard_suite, DASHBOARDS
    from velora_projectone.projectone.reports.dashboard_intelligence import (filter_dashboard_data, dashboard_drilldown, trend_series, validate_dashboard_view, build_dashboard_snapshot)
    from velora_projectone.projectone.services.ai_assist import project_insights
    from velora_projectone.projectone.services.resource_management import (validate_resource_profile, match_resource_skills as match_resource_competencies, build_resource_capacity, validate_allocation, evaluate_utilisation, level_resource_assignments, validate_timesheet as validate_resource_timesheet)
    from velora_projectone.projectone.services.advanced_schedule import calculate_cpm, calculate_gantt, compare_schedule_to_baseline, preview_schedule_change
    from velora_projectone.projectone.services.project_financial_control import (
        validate_budget_version, validate_budget_allocation, validate_budget_change,
        validate_posted_actual, aggregate_actual_costs, validate_revenue_forecast,
        validate_posted_revenue, aggregate_recognised_revenue, project_financial_forecast,
        category_cost_control, portfolio_financial_rollup,
        calculate_revenue_recognition, calculate_earned_value,
        validate_performance_obligation,
    )

    from velora_projectone.projectone.services.portfolio_intelligence import (
        prioritise_portfolio, model_portfolio_scenario, analyse_cross_project_dependencies,
        forecast_enterprise_capacity, build_portfolio_exception_register,
    )
    from velora_projectone.projectone.services.performance_optimisation import (
        forecast_earned_value, analyse_schedule_trend, optimise_resource_conflicts,
        portfolio_profitability_trend, schedule_benefit_reviews, build_management_alerts,
    )
    from velora_projectone.projectone.services.governance import (
        evaluate_stage_gate, assess_change_impact, validate_document_revision,
        evaluate_closure_checklist, calculate_benefit_realisation,
    )

    @app.post("/api/projectone/governance/stage-gate/evaluate")
    def projectone_stage_gate_evaluate(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: evaluate_stage_gate(data.get("criteria", []),
                    data.get("evidence", {}), waiver_reason=data.get("waiver_reason")))

    @app.post("/api/projectone/governance/change-impact")
    def projectone_change_impact(request: Request, body: dict = Body(default={})):
        data = body or {}
        allowed = {k: data[k] for k in ("schedule_days", "cost_delta", "scope_change", "risk_change", "quality_change", "thresholds") if k in data}
        return run(request, lambda: assess_change_impact(**allowed))

    @app.post("/api/projectone/governance/document-revision/validate")
    def projectone_document_revision_validate(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: validate_document_revision(**data))

    @app.post("/api/projectone/governance/closure/readiness")
    def projectone_closure_readiness(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: evaluate_closure_checklist(data.get("checklist", {}),
                    lessons_learned=data.get("lessons_learned", ""), benefits_owner=data.get("benefits_owner")))

    @app.post("/api/projectone/governance/benefit/realisation")
    def projectone_benefit_realisation(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: calculate_benefit_realisation(**data))

    # Advanced portfolio intelligence: deterministic read models only. Every
    # request requires authenticated portfolio-read permission. Input rows are
    # analytical payloads; production dashboards should source factual rows via
    # the host's authorised source adapters, not trust browser-supplied actuals.
    def _projectone_portfolio_actor(request):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        bridge = native_integration_registry.get()
        actor = getattr(request.state, "projectone_actor", None)
        if bridge is None or not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Configured native integration and authenticated actor are required.")
        bridge.assert_permission(actor, "projectone.portfolio.read")
        return actor

    def _projectone_programme_provider(request, actor):
        """Resolve the explicit host read adapter; never accept browser source rows."""
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        bridge = native_integration_registry.get()
        bridge.assert_permission(actor, "projectone.programme.read")
        provider = getattr(request.state, "projectone_programme_data_provider", None)
        if provider is None:
            raise RuntimeError("Programme data provider is not configured; client-supplied source records are not accepted.")
        return provider

    @app.get("/api/projectone/portfolio/executive-workspace")
    def projectone_executive_workspace(request: Request, project_id: str | None = None,
                                      modified_since: str | None = None):
        """Compose executive workspace from tenant-scoped host source adapters.

        Only source permissions held by the trusted principal are requested.
        Missing permissions/adapters are reported as incomplete coverage, not
        represented as zero-valued business facts.
        """
        from velora_projectone.projectone.reports.executive_workspace import build_executive_workspace
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            bridge.assert_permission(actor, "projectone.portfolio.read")
            requested = {
                "accounting": ["project_positions", "cost_actuals", "recognised_revenue"],
                "hrms": ["resources", "allocations"],
                "procurement": ["commitments"],
                "sales": ["billing_milestones"],
                "inventory": ["material_usage", "stock_commitments"],
                "fixed_assets": ["asset_allocations"],
            }
            if "projectone.integration.read_all" not in actor.permissions:
                requested = {name: collections for name, collections in requested.items()
                             if f"projectone.integration.{name}.read" in actor.permissions}
            if not requested:
                return {"company_scope": actor.company_id, "project_scope": project_id,
                        "financial_by_currency": [], "source_health": {"sources": {},
                        "connected_count": 0, "source_count": 0,
                        "qualification": "No upstream source-read permissions are assigned."},
                        "data_quality": {"issue_count": 0, "high_count": 0, "issues": [], "truncated": False},
                        "record_counts": {}, "metadata": {"read_only": True,
                        "coverage": "No source permissions; no business metrics inferred."}}
            collected = bridge.read_integration().collect(actor, requested,
                project_id=project_id, modified_since=modified_since)
            return build_executive_workspace(collected)
        return run(request, build)

    @app.post("/api/projectone/portfolio/prioritisation")
    def projectone_portfolio_prioritisation(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_portfolio_actor(request)
            return prioritise_portfolio(data.get("projects", []), weights=data.get("weights"))
        return run(request, build)

    @app.post("/api/projectone/portfolio/scenario")
    def projectone_portfolio_scenario(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_portfolio_actor(request)
            return model_portfolio_scenario(data.get("projects", []), actions=data.get("actions", {}),
                                            contingency_percent=data.get("contingency_percent", 0))
        return run(request, build)

    @app.post("/api/projectone/portfolio/dependencies/analyse")
    def projectone_portfolio_dependencies(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_portfolio_actor(request)
            return analyse_cross_project_dependencies(data.get("dependencies", []))
        return run(request, build)

    @app.post("/api/projectone/portfolio/capacity-forecast")
    def projectone_portfolio_capacity(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_portfolio_actor(request)
            return forecast_enterprise_capacity(data.get("demand", []), data.get("capacity", []))
        return run(request, build)

    @app.post("/api/projectone/portfolio/exceptions")
    def projectone_portfolio_exceptions(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_portfolio_actor(request)
            return build_portfolio_exception_register(data.get("projects", []),
                schedule_tolerance_days=data.get("schedule_tolerance_days", 10),
                cost_tolerance_percent=data.get("cost_tolerance_percent", 10))
        return run(request, build)

    def _projectone_advanced_portfolio_actor(request):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        bridge = native_integration_registry.get()
        actor = getattr(request.state, "projectone_actor", None)
        if bridge is None or not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Configured native integration and authenticated actor are required.")
        bridge.assert_permission(actor, "projectone.portfolio.read")
        return actor

    def _projectone_programme_provider(request, actor):
        """Resolve the explicit host read adapter; never accept browser source rows."""
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        bridge = native_integration_registry.get()
        bridge.assert_permission(actor, "projectone.programme.read")
        provider = getattr(request.state, "projectone_programme_data_provider", None)
        if provider is None:
            raise RuntimeError("Programme data provider is not configured; client-supplied source records are not accepted.")
        return provider

    @app.post("/api/projectone/performance/earned-value-forecast")
    def projectone_earned_value_forecast(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return forecast_earned_value(**data)
        return run(request, build)

    @app.post("/api/projectone/performance/schedule-trend")
    def projectone_schedule_trend(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return analyse_schedule_trend(data.get("observations", []))
        return run(request, build)

    @app.post("/api/projectone/resources/conflict-optimisation")
    def projectone_resource_conflict_optimisation(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return optimise_resource_conflicts(data.get("activities", []), data.get("capacities", []))
        return run(request, build)

    @app.post("/api/projectone/portfolio/profitability-trend")
    def projectone_profitability_trend(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return portfolio_profitability_trend(data.get("observations", []))
        return run(request, build)

    @app.post("/api/projectone/benefits/review-schedule")
    def projectone_benefit_review_schedule(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return schedule_benefit_reviews(data.get("benefits", []), data.get("as_of_period", ""))
        return run(request, build)

    @app.post("/api/projectone/portfolio/management-alerts")
    def projectone_management_alerts(request: Request, body: dict = Body(default={})):
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return build_management_alerts(data.get("exceptions", []), owners=data.get("owners"))
        return run(request, build)

    # v2.14 enterprise delivery controls. These are deterministic read models;
    # host authentication and portfolio-read permission are mandatory.
    @app.post("/api/projectone/portfolio/delivery-forecast")
    def projectone_portfolio_delivery_forecast(request: Request, body: dict = Body(default={})):
        from velora_projectone.projectone.services.enterprise_controls import forecast_portfolio_delivery
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return forecast_portfolio_delivery(data.get("projects", []))
        return run(request, build)

    @app.post("/api/projectone/programmes/critical-path")
    def projectone_programme_critical_path(request: Request, body: dict = Body(default={})):
        from velora_projectone.projectone.services.enterprise_controls import analyse_programme_critical_path
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return analyse_programme_critical_path(data.get("milestones", []), data.get("dependencies", []))
        return run(request, build)

    # v2.15 programme intelligence. Source records are loaded by an injected
    # host provider after trusted actor and programme permission checks. Browser
    # payloads contain selectors/assumptions only, never authoritative source rows.
    @app.post("/api/projectone/programmes/calendar-schedule")
    def projectone_programme_calendar_schedule(request: Request, body: dict = Body(default={})):
        from velora_projectone.projectone.services.programme_intelligence import programme_calendar_schedule
        data = body or {}
        def build():
            actor = _projectone_advanced_portfolio_actor(request)
            provider = _projectone_programme_provider(request, actor)
            programme_id = str(data.get("programme_id") or "").strip()
            if not programme_id: raise ValueError("programme_id is required")
            source = provider.read_programme_schedule(actor, programme_id)
            return programme_calendar_schedule(source["activities"], data.get("project_start") or source.get("project_start"),
                source.get("working_weekdays", [0,1,2,3,4]), source.get("holidays", []))
        return run(request, build)

    @app.post("/api/projectone/programmes/risk-simulation")
    def projectone_programme_risk_simulation(request: Request, body: dict = Body(default={})):
        from velora_projectone.projectone.services.programme_intelligence import simulate_programme_risk
        data = body or {}
        def build():
            actor = _projectone_advanced_portfolio_actor(request)
            provider = _projectone_programme_provider(request, actor)
            programme_id = str(data.get("programme_id") or "").strip()
            if not programme_id: raise ValueError("programme_id is required")
            source = provider.read_programme_risk_model(actor, programme_id)
            return simulate_programme_risk(source["activities"], source.get("risks", []),
                iterations=data.get("iterations", 1000), seed=data.get("seed", 17),
                project_start=source.get("project_start"), working_weekdays=source.get("working_weekdays", [0,1,2,3,4]),
                holidays=source.get("holidays", []), base_cost=source.get("base_cost", 0))
        return run(request, build)

    @app.post("/api/projectone/programmes/cost-resource-position")
    def projectone_programme_cost_resource_position(request: Request, body: dict = Body(default={})):
        from velora_projectone.projectone.services.programme_intelligence import programme_cost_resource_position
        data = body or {}
        def build():
            actor = _projectone_advanced_portfolio_actor(request)
            provider = _projectone_programme_provider(request, actor)
            programme_id = str(data.get("programme_id") or "").strip()
            if not programme_id: raise ValueError("programme_id is required")
            source = provider.read_programme_cost_resource_position(actor, programme_id)
            return programme_cost_resource_position(source["projects"])
        return run(request, build)

    @app.post("/api/projectone/portfolio/scenario-comparison")
    def projectone_portfolio_scenario_comparison(request: Request, body: dict = Body(default={})):
        from velora_projectone.projectone.services.programme_intelligence import compare_portfolio_scenarios
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return compare_portfolio_scenarios(data.get("scenarios", []))
        return run(request, build)

    @app.post("/api/projectone/management/interventions/{exception_id}/submit")
    def projectone_submit_intervention(request: Request, exception_id: str, body: dict = Body(default={})):
        from velora_projectone.projectone.services.programme_intelligence import build_intervention_submission
        data = body or {}
        def build():
            actor = _projectone_advanced_portfolio_actor(request)
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            native_integration_registry.get().assert_permission(actor, "projectone.intervention.submit")
            submitter = getattr(request.state, "projectone_intervention_submitter", None)
            if not callable(submitter):
                raise RuntimeError("Host intervention submitter is not configured; no corrective action was created.")
            envelope = build_intervention_submission(exception_id, data, actor.actor_id)
            # Host port owns permission checks, atomic document creation, workflow submission and audit.
            return submitter(actor, envelope)
        return run(request, build)

    @app.post("/api/projectone/management/intervention-centre")
    def projectone_intervention_centre(request: Request, body: dict = Body(default={})):
        from velora_projectone.projectone.services.enterprise_controls import build_intervention_centre
        data = body or {}
        def build():
            _projectone_advanced_portfolio_actor(request)
            return build_intervention_centre(data.get("exceptions", []), data.get("actions", []),
                                             as_of_period=data.get("as_of_period"))
        return run(request, build)

    @app.get("/api/projectone/health")
    def projectone_health(request: Request):
        return run(request, lambda: {"application": "Velora ProjectOne", "version": __import__("velora_projectone").__version__, "status": "available"})

    # Native Velora integration endpoints. Identity/company are injected by the
    # host authentication middleware; request-body identity fields are ignored.
    @app.get("/api/projectone/integrations/readiness")
    def projectone_integration_readiness(request: Request):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.health import integration_health
        def build():
            bridge = native_integration_registry.get()
            native = native_integration_registry.readiness()
            if bridge is None or not bridge.capabilities().source_registry:
                return {"native": native, "sources": None}
            source_status = getattr(request.state, "projectone_source_status", {})
            source_readiness = bridge.read_integration().readiness()
            return {"native": native, "sources": integration_health(source_readiness, source_status=source_status)}
        return run(request, build)

    # Native persistence endpoints for the approved core ProjectOne DocTypes.
    @app.get("/api/projectone/native/documents/{doctype}/{name}")
    def projectone_native_document_get(request: Request, doctype: str, name: str):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        def build():
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            return bridge.document_repository().get(actor, doctype, name)
        return run(request, build)

    @app.get("/api/projectone/native/documents/{doctype}")
    def projectone_native_document_list(request: Request, doctype: str, limit: int = 100,
                                        offset: int = 0, status: str | None = None,
                                        project: str | None = None):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        def build():
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            filters = {k: v for k, v in {"status": status, "project": project}.items() if v is not None}
            return bridge.document_repository().list(actor, doctype, filters=filters,
                                                     limit=limit, offset=offset)
        return run(request, build)

    @app.post("/api/projectone/native/documents/{doctype}")
    def projectone_native_document_insert(request: Request, doctype: str, body: dict = Body(default={})):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        def build():
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            data = body or {}
            return bridge.document_repository().insert(actor, doctype, data.get("document"),
                                                         idempotency_key=data.get("idempotency_key"))
        return run(request, build)

    @app.put("/api/projectone/native/documents/{doctype}/{name}")
    def projectone_native_document_update(request: Request, doctype: str, name: str,
                                          body: dict = Body(default={})):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        def build():
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            data = body or {}
            return bridge.document_repository().update(actor, doctype, name, data.get("document"),
                                                         expected_version=data.get("expected_version"))
        return run(request, build)

    @app.post("/api/projectone/native/workflow/{doctype}/{name}/{action}")
    def projectone_native_workflow_action(request: Request, doctype: str, name: str,
                                          action: str, body: dict = Body(default={})):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        def build():
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            data = body or {}
            if set(data) - {"evidence"}:
                raise ValueError("Only workflow evidence may be supplied; actor, company and target state are host controlled.")
            return bridge.workflow_action(actor, doctype, name, action, data.get("evidence"))
        return run(request, build)

    @app.get("/api/projectone/native/workflow-inbox")
    def projectone_native_workflow_inbox(request: Request, limit: int = 100):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        def build():
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            return bridge.pending_workflow_items(actor, limit=limit)
        return run(request, build)

    @app.post("/api/projectone/integrations/collect")
    def projectone_integration_collect(request: Request, body: dict = Body(default={})):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        def build():
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None:
                raise RuntimeError("Native Velora integration is not configured.")
            if not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Authenticated Velora actor context is required.")
            data = body or {}
            project_id = data.get("project_id")
            if project_id:
                bridge.assert_permission(actor, "projectone.project.read", project_id=project_id)
            else:
                bridge.assert_permission(actor, "projectone.portfolio.read")
            requests = data.get("requests")
            return bridge.read_integration().collect(
                actor, requests, project_id=project_id,
                modified_since=data.get("modified_since"),
            )
        return run(request, build)

    @app.post("/api/projectone/dashboards/live")
    def projectone_live_dashboard_suite(request: Request, body: dict = Body(default={})):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        def build():
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            data = body or {}
            project_id = data.get("project_id")
            permission = "projectone.project.read" if project_id else "projectone.portfolio.read"
            bridge.assert_permission(actor, permission, project_id=project_id)
            collected = bridge.collect_dashboard_data(
                actor, project_id=project_id,
                modified_since=data.get("modified_since"),
                limit=min(max(int(data.get("limit", 500)), 1), 500),
            )
            payload = dict(collected.get("data", {}))
            filters = data.get("filters", {})
            return {"dashboards": build_dashboard_suite(filter_dashboard_data(payload, filters)),
                    "provenance": collected.get("provenance"),
                    "permission_denied_collections": collected.get("permission_denied_collections", []),
                    "scope": collected.get("scope"),
                    "metadata": collected.get("metadata"),
                    "read_only": True}
        return run(request, build)

    @app.post("/api/projectone/metrics/earned-value")
    def projectone_earned_value(request: Request, body: dict = Body(default={})):
        return run(request, lambda: calculate_earned_value(**(body or {})))

    @app.post("/api/projectone/metrics/risk-score")
    def projectone_risk_score(request: Request, body: dict = Body(default={})):
        return run(request, lambda: score_risk(**(body or {})))

    @app.post("/api/projectone/schedule/cpm")
    def projectone_cpm(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: calculate_cpm(data.get("activities", [])))

    @app.post("/api/projectone/schedule/gantt")
    def projectone_gantt(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: calculate_gantt(data.get("activities", []), data.get("project_start"), tuple(data.get("working_weekdays", [0,1,2,3,4])), data.get("holidays", [])))

    @app.post("/api/projectone/schedule/baseline/compare")
    def projectone_baseline_compare(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: compare_schedule_to_baseline(data.get("current", []), data.get("baseline", [])))

    @app.post("/api/projectone/schedule/projects/{project_id}/tasks")
    def projectone_schedule_create_task(request: Request, project_id: str, body: dict = Body(default={} )):
        data = body or {}
        def build():
            import math
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            allowed = {"task_code", "title", "wbs", "parent_task", "assignee", "team", "priority",
                       "planned_start", "planned_finish", "duration_days", "estimated_hours", "description"}
            if set(data) - (allowed | {"idempotency_key"}):
                raise ValueError("Unsupported task fields; company, actor, status and system fields are host controlled.")
            if not data.get("task_code") or not data.get("title"):
                raise ValueError("task_code and title are required.")
            duration = data.get("duration_days", 0)
            if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
                raise ValueError("duration_days must be a non-negative integer.")
            from datetime import date
            for field in ("planned_start", "planned_finish"):
                if data.get(field):
                    try: date.fromisoformat(str(data[field]))
                    except ValueError as exc: raise ValueError(f"{field} must use ISO YYYY-MM-DD format.") from exc
            if data.get("planned_start") and data.get("planned_finish") and data["planned_finish"] < data["planned_start"]:
                raise ValueError("planned_finish cannot precede planned_start.")
            hours = data.get("estimated_hours")
            if hours is not None and (isinstance(hours, bool) or not isinstance(hours, (int, float)) or not math.isfinite(hours) or hours < 0):
                raise ValueError("estimated_hours must be a finite non-negative number.")
            bridge.assert_permission(actor, "projectone.task.create", project_id=project_id)
            doc = {k:v for k,v in data.items() if k in allowed}
            doc.update({"project": project_id, "status": "Draft", "progress_percent": 0})
            return bridge.document_repository().insert(actor, "Project Task", doc,
                                                        idempotency_key=data.get("idempotency_key"))
        return run(request, build)

    @app.put("/api/projectone/schedule/tasks/{task_id}")
    def projectone_schedule_update_task(request: Request, task_id: str, body: dict = Body(default={} )):
        data = body or {}
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            if set(data) != {"expected_version", "changes"} or not isinstance(data.get("changes"), dict):
                raise ValueError("Supply only expected_version and a changes object.")
            current = bridge.document_repository().get(actor, "Project Task", task_id)
            if not current: raise KeyError(task_id)
            allowed = {"title", "description", "wbs", "parent_task", "assignee", "team", "priority", "estimated_hours"}
            changes = data["changes"]
            if not changes or set(changes) - allowed:
                raise ValueError("Only descriptive, assignment and estimate fields can be edited here. Dates and status require governed commands.")
            bridge.assert_permission(actor, "projectone.task.update", project_id=current.get("project"))
            return bridge.document_repository().update(actor, "Project Task", task_id, changes,
                                                       expected_version=data.get("expected_version"))
        return run(request, build)

    @app.post("/api/projectone/schedule/projects/{project_id}/dependencies")
    def projectone_schedule_create_dependency(request: Request, project_id: str, body: dict = Body(default={} )):
        data = body or {}
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            allowed = {"predecessor", "successor", "relationship", "lag_days", "active", "idempotency_key"}
            if set(data) - allowed: raise ValueError("Unexpected dependency fields.")
            pred = bridge.document_repository().get(actor, "Project Task", data.get("predecessor"))
            succ = bridge.document_repository().get(actor, "Project Task", data.get("successor"))
            if not pred or not succ or pred.get("project") != project_id or succ.get("project") != project_id:
                raise ValueError("Both dependency tasks must belong to the selected project.")
            if pred.get("name") == succ.get("name"):
                raise ValueError("A task cannot depend on itself.")
            relation = data.get("relationship", "Finish to Start")
            if relation not in {"Finish to Start", "Start to Start", "Finish to Finish", "Start to Finish"}:
                raise ValueError("Unsupported dependency relationship.")
            lag = data.get("lag_days", 0)
            if isinstance(lag, bool) or not isinstance(lag, int): raise ValueError("lag_days must be an integer.")
            active = data.get("active", 1)
            if active not in (0, 1, False, True): raise ValueError("active must be a boolean or 0/1.")
            bridge.assert_permission(actor, "projectone.task_dependency.create", project_id=project_id)
            repo = bridge.document_repository()
            from velora_projectone.projectone.integrations.native_schedule import validate_dependency_graph
            tasks = repo.list(actor, "Project Task", filters={"project": project_id}, limit=500)
            dependencies = repo.list(actor, "Task Dependency", filters={"project": project_id}, limit=500)
            candidate = {"predecessor": pred["name"], "successor": succ["name"],
                         "relationship": relation, "lag_days": lag, "active": int(active)}
            validate_dependency_graph(tasks, dependencies, candidate)
            return repo.insert(actor, "Task Dependency", {"project":project_id, **candidate},
                               idempotency_key=data.get("idempotency_key"))
        return run(request, build)

    @app.put("/api/projectone/schedule/dependencies/{dependency_id}")
    def projectone_schedule_update_dependency(request: Request, dependency_id: str, body: dict = Body(default={} )):
        data = body or {}
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            from velora_projectone.projectone.integrations.native_schedule import validate_dependency_graph
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            if set(data) != {"expected_version", "changes"} or not isinstance(data.get("changes"), dict):
                raise ValueError("Supply expected_version and a changes object.")
            expected = data["expected_version"]
            if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
                raise ValueError("A positive expected_version is required.")
            changes = data["changes"]
            allowed = {"predecessor", "successor", "relationship", "lag_days", "active"}
            if not changes or set(changes) - allowed:
                raise ValueError("Only dependency endpoints, relationship, lag and active status may be changed.")
            repo = bridge.document_repository(); current = repo.get(actor, "Task Dependency", dependency_id)
            if not current:
                raise KeyError(dependency_id)
            project_id = current.get("project")
            bridge.assert_permission(actor, "projectone.task_dependency.update", project_id=project_id)
            if current.get("version") != expected:
                from velora_projectone.projectone.services.persistence import VersionConflict
                raise VersionConflict("Dependency changed; reload before editing.")
            merged = {**current, **changes}
            for field in ("predecessor", "successor"):
                task = repo.get(actor, "Project Task", merged.get(field))
                if not task or task.get("project") != project_id:
                    raise ValueError("Both dependency endpoints must belong to the dependency project.")
            if merged.get("relationship") not in {"Finish to Start", "Start to Start", "Finish to Finish", "Start to Finish"}:
                raise ValueError("Unsupported dependency relationship.")
            lag = merged.get("lag_days", 0)
            if isinstance(lag, bool) or not isinstance(lag, int):
                raise ValueError("lag_days must be an integer.")
            if merged.get("active", 1) not in (0, 1, False, True):
                raise ValueError("active must be a boolean or 0/1.")
            tasks = repo.list(actor, "Project Task", filters={"project": project_id}, limit=500)
            dependencies = repo.list(actor, "Task Dependency", filters={"project": project_id}, limit=500)
            validate_dependency_graph(tasks, dependencies, merged, exclude_id=dependency_id)
            return repo.update(actor, "Task Dependency", dependency_id, changes, expected_version=expected)
        return run(request, build)

    @app.get("/api/projectone/schedule/projects/{project_id}/live")
    def projectone_live_schedule(request: Request, project_id: str,
                                 working_weekdays: str | None = None):
        """Load native Project, Project Task, Task Dependency and approved baseline records."""
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            from velora_projectone.projectone.integrations.native_schedule import build_live_schedule
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            days = None if working_weekdays in (None, "") else tuple(int(v) for v in working_weekdays.split(",") if v.strip() != "")
            if days is not None and (not days or any(v < 0 or v > 6 for v in days) or len(set(days)) != len(days)):
                raise ValueError("working_weekdays must be unique weekday numbers from 0 to 6.")
            bridge.assert_permission(actor, "projectone.project.read", project_id=project_id)
            return build_live_schedule(bridge.document_repository(), actor, project_id,
                                       working_weekdays=days)
        return run(request, build)

    @app.post("/api/projectone/schedule/change-requests")
    def projectone_schedule_change_request(request: Request, body: dict = Body(default={})):
        """Create an impact-backed schedule change and submit it to native workflow."""
        data = body or {}
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            from velora_projectone.projectone.integrations.native_schedule import create_schedule_change_request
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            allowed = {"project_id", "task_id", "proposed_start_offset", "reason", "title", "idempotency_key", "working_weekdays"}
            if set(data) - allowed:
                raise ValueError("Unexpected fields; actor, company, approval state and task dates are host controlled.")
            days = tuple(data["working_weekdays"]) if data.get("working_weekdays") is not None else None
            return create_schedule_change_request(bridge, actor, data.get("project_id"),
                task_id=data.get("task_id"), proposed_start_offset=data.get("proposed_start_offset"),
                reason=data.get("reason"), title=data.get("title"),
                idempotency_key=data.get("idempotency_key"), working_weekdays=days)
        return run(request, build)

    @app.post("/api/projectone/schedule/change-requests/{name}/apply-approved")
    def projectone_apply_approved_schedule_change(request: Request, name: str):
        """Apply only an approved schedule request; all task writes are atomic and version checked."""
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            from velora_projectone.projectone.integrations.native_schedule import apply_approved_schedule_change
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            return apply_approved_schedule_change(bridge, actor, name)
        return run(request, build)

    @app.post("/api/projectone/schedule/preview-change")
    def projectone_schedule_preview_change(request: Request, body: dict = Body(default={})):
        """Authenticated schedule what-if; never writes task or baseline records."""
        data = body or {}
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get()
            actor = getattr(request.state, "projectone_actor", None)
            project_id = str(data.get("project_id") or "").strip()
            if bridge is None or not isinstance(actor, AuthenticatedActor) or not project_id:
                raise PermissionError("Configured native integration, authenticated actor and project_id are required.")
            bridge.assert_permission(actor, "projectone.project.read", project_id=project_id)
            return preview_schedule_change(data.get("activities", []), data.get("project_start"),
                data.get("task_id"), data.get("proposed_start_offset"),
                tuple(data.get("working_weekdays", [0,1,2,3,4])), data.get("holidays", []),
                baseline=data.get("baseline"))
        return run(request, build)

    @app.post("/api/projectone/metrics/schedule")
    def projectone_schedule(request: Request, body: dict = Body(default={})):
        return run(request, lambda: calculate_schedule((body or {}).get("activities", [])))

    @app.post("/api/projectone/metrics/budget-position")
    def projectone_budget_position(request: Request, body: dict = Body(default={})):
        return run(request, lambda: calculate_budget_position(**(body or {})))

    @app.post("/api/projectone/validation/project")
    def projectone_validate_project(request: Request, body: dict = Body(default={} )):
        return run(request, lambda: {"valid": validate_project(body or {})})

    @app.post("/api/projectone/lifecycle/transition")
    def projectone_lifecycle_transition(request: Request, body: dict = Body(default={} )):
        data = body or {}
        return run(request, lambda: transition_project(data.get("current_status"), data.get("target_status"), data.get("evidence")))

    @app.post("/api/projectone/calendar/add-working-days")
    def projectone_add_working_days(request: Request, body: dict = Body(default={} )):
        data = body or {}
        return run(request, lambda: {"result": add_working_days(data.get("start_date"), int(data.get("days", 0)), tuple(data.get("working_weekdays", [0,1,2,3,4])), data.get("holidays", []))})

    @app.post("/api/projectone/calendar/working-days-between")
    def projectone_working_days_between(request: Request, body: dict = Body(default={} )):
        data = body or {}
        return run(request, lambda: {"working_days": working_days_between(data.get("start_date"), data.get("end_date"), tuple(data.get("working_weekdays", [0,1,2,3,4])), data.get("holidays", []))})

    @app.post("/api/projectone/resources/capacity")
    def projectone_resource_capacity(request: Request, body: dict = Body(default={} )):
        data = body or {}
        capacities = {(x["resource_id"], x["period"]): x["capacity_hours"] for x in data.get("capacities", [])}
        return run(request, lambda: evaluate_resource_capacity(capacities, data.get("allocations", [])))

    @app.post("/api/projectone/resources/labour-cost")
    def projectone_labour_cost(request: Request, body: dict = Body(default={} )):
        data = body or {}
        return run(request, lambda: calculate_labour_cost(data.get("hours"), data.get("cost_rate")))

    @app.post("/api/projectone/finance/reconcile-commitment")
    def projectone_reconcile_commitment(request: Request, body: dict = Body(default={} )):
        data = body or {}
        return run(request, lambda: reconcile_commitment(data.get("source_order_amount"), data.get("invoiced_against_order"), data.get("cancelled_amount", 0)))

    @app.post("/api/projectone/finance/position")
    def projectone_financial_position(request: Request, body: dict = Body(default={} )):
        data = body or {}
        return run(request, lambda: calculate_project_financial_position(**data))

    @app.post("/api/projectone/integrations/validate-source-reference")
    def projectone_validate_source_reference(request: Request, body: dict = Body(default={} )):
        data = body or {}
        return run(request, lambda: validate_source_reference(**data))

    @app.post("/api/projectone/reports/portfolio-summary")
    def projectone_portfolio_summary(request: Request, body: dict = Body(default={} )):
        data = body or {}
        return run(request, lambda: build_portfolio_summary(data.get("projects", [])))


    # Domain endpoints: repository persistence is injected by the host adapter.
    @app.post("/api/projectone/schedule/dated")
    def projectone_dated_schedule(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: calculate_dated_schedule(data.get("activities", []), data.get("project_start"), tuple(data.get("working_weekdays", [0,1,2,3,4])), data.get("holidays", [])))

    @app.post("/api/projectone/resources/skills/match")
    def projectone_match_skills(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: {"matches": match_resource_skills(data.get("requirements", []), data.get("resources", []))})

    @app.post("/api/projectone/resources/level")
    def projectone_level_resources(request: Request, body: dict = Body(default={})):
        data = body or {}
        capacities = {(x["resource_id"], x["period"]): x["capacity_hours"] for x in data.get("capacities", [])}
        return run(request, lambda: level_allocations(data.get("activities", []), capacities))

    @app.post("/api/projectone/finance/forecast")
    def projectone_cost_forecast(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: cost_forecast(**data))

    @app.post("/api/projectone/commercial/contract/validate")
    def projectone_validate_contract(request: Request, body: dict = Body(default={})):
        return run(request, lambda: validate_contract(body or {}))

    @app.post("/api/projectone/commercial/billing-position")
    def projectone_billing_position(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: billing_position(**data))

    @app.post("/api/projectone/agile/sprint/validate")
    def projectone_validate_sprint(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: validate_sprint(data.get("sprint", {}), data.get("stories", [])))

    @app.post("/api/projectone/agile/sprint/metrics")
    def projectone_sprint_metrics(request: Request, body: dict = Body(default={})):
        return run(request, lambda: sprint_metrics((body or {}).get("stories", [])))

    @app.post("/api/projectone/agile/story/validate")
    def projectone_validate_story(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: validate_story(data.get("story", {}), require_ready=data.get("require_ready", False)))

    @app.post("/api/projectone/agile/story/transition")
    def projectone_transition_story(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: transition_story(data.get("story", {}), data.get("new_status")))

    @app.post("/api/projectone/agile/sprint/plan")
    def projectone_plan_sprint(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: plan_sprint(data.get("sprint", {}), data.get("backlog", []), team_capacity_hours=data.get("team_capacity_hours")))

    @app.post("/api/projectone/agile/kanban")
    def projectone_kanban(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: kanban_board(data.get("stories", []), wip_limits=data.get("wip_limits")))

    @app.post("/api/projectone/agile/sprint/burndown")
    def projectone_sprint_burndown(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: burndown(data.get("sprint", {}), data.get("stories", []), daily_completed=data.get("daily_completed")))

    @app.post("/api/projectone/agile/sprint/review")
    def projectone_sprint_review(request: Request, body: dict = Body(default={})):
        return run(request, lambda: sprint_review((body or {}).get("stories", [])))

    @app.post("/api/projectone/agile/retrospective/validate")
    def projectone_validate_retrospective(request: Request, body: dict = Body(default={})):
        return run(request, lambda: validate_retrospective(body or {}))


    # Enterprise resource management: pure calculations; host authorization and persistence
    # remain mandatory at the application boundary.
    @app.post("/api/projectone/resources/profile/validate")
    def projectone_resource_profile_validate(request: Request, body: dict = Body(default={})):
        return run(request, lambda: validate_resource_profile(body or {}))

    @app.post("/api/projectone/resources/skills/rank")
    def projectone_resource_skill_rank(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: {"matches": match_resource_competencies(data.get("requirements", []), data.get("resources", []))})

    @app.post("/api/projectone/resources/capacity/calendar")
    def projectone_resource_capacity_calendar(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: build_resource_capacity(data.get("resources", []), start_date=data.get("start_date"), end_date=data.get("end_date"), allocations=data.get("allocations", []), exceptions=data.get("exceptions", []), calendars=data.get("calendars", {}), working_weekdays=tuple(data.get("working_weekdays", [0,1,2,3,4])), holidays=data.get("holidays", [])))

    @app.post("/api/projectone/resources/allocation/validate")
    def projectone_resource_allocation_validate(request: Request, body: dict = Body(default={})):
        return run(request, lambda: validate_allocation(body or {}))

    @app.post("/api/projectone/resources/utilisation")
    def projectone_resource_utilisation(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: evaluate_utilisation(data.get("capacity_rows", []), warning_threshold=data.get("warning_threshold", "0.85")))

    @app.post("/api/projectone/resources/level-calendar")
    def projectone_resource_level_calendar(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: level_resource_assignments(data.get("assignments", []), {(x["resource_id"], x["date"]): x["available_hours"] for x in data.get("capacity_rows", [])}))

    # Timesheet state changes and payroll hand-off are deliberately exposed only
    # through the authenticated host workflow/integration adapter, not caller-supplied
    # actor/company IDs in a public JSON body.


    # Project Financial Management: validation and read-model calculations only.
    # Budget approvals and source-system imports are persisted through trusted host adapters.
    @app.post("/api/projectone/finance/budget/validate-version")
    def projectone_budget_validate_version(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: validate_budget_version(data.get("budget", {}), data.get("prior_versions", [])))

    @app.post("/api/projectone/finance/budget/validate-allocation")
    def projectone_budget_validate_allocation(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: validate_budget_allocation(data.get("budget", {}), data.get("lines", [])))

    @app.post("/api/projectone/finance/budget-change/validate")
    def projectone_budget_change_validate(request: Request, body: dict = Body(default={})):
        return run(request, lambda: validate_budget_change(body or {}))

    @app.post("/api/projectone/finance/actual/validate-source")
    def projectone_actual_validate_source(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: validate_posted_actual(data.get("actual", {}), data.get("existing_source_keys", [])))

    @app.post("/api/projectone/finance/actuals/aggregate")
    def projectone_actuals_aggregate(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: aggregate_actual_costs(data.get("actuals", []), project=data.get("project"), currency=data.get("currency"), as_at=data.get("as_at")))


    @app.post("/api/projectone/finance/revenue/forecast/validate")
    def projectone_revenue_forecast_validate(request: Request, body: dict = Body(default={})):
        return run(request, lambda: validate_revenue_forecast(body or {}))

    @app.post("/api/projectone/finance/revenue/validate-source")
    def projectone_revenue_validate_source(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: validate_posted_revenue(data.get("revenue", {}), data.get("existing_source_keys", [])))

    @app.post("/api/projectone/finance/revenue/aggregate")
    def projectone_revenue_aggregate(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: aggregate_recognised_revenue(data.get("revenues", []), project=data.get("project"), currency=data.get("currency"), as_at=data.get("as_at")))

    @app.post("/api/projectone/finance/forecast/project")
    def projectone_project_financial_forecast(request: Request, body: dict = Body(default={})):
        return run(request, lambda: project_financial_forecast(**(body or {})))

    @app.post("/api/projectone/finance/control/by-category")
    def projectone_category_cost_control(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: category_cost_control(data.get("budget_lines", []), data.get("actuals", []), data.get("commitments", []), data.get("estimates", []), currency=data.get("currency")))

    @app.post("/api/projectone/finance/performance-obligation/validate")
    def projectone_performance_obligation_validate(request: Request, body: dict = Body(default={})):
        return run(request, lambda: validate_performance_obligation(body or {}))

    @app.post("/api/projectone/finance/revenue-recognition/calculate")
    def projectone_revenue_recognition_calculate(request: Request, body: dict = Body(default={})):
        return run(request, lambda: calculate_revenue_recognition(**(body or {})))

    # Native, tenant-scoped financial commands. These routes use the authenticated
    # Velora actor, document engine, permission resolver, transaction, audit and
    # workflow adapters. Recognition source values are never accepted from clients.
    def _projectone_finance_commands(request):
        from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
        from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
        from velora_projectone.projectone.services.project_finance_commands import ProjectFinanceCommandService
        bridge = native_integration_registry.get()
        actor = getattr(request.state, "projectone_actor", None)
        if bridge is None or not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Configured native Velora integration and authenticated actor are required.")
        provider = getattr(request.state, "projectone_finance_data_provider", None)
        return ProjectFinanceCommandService(bridge, recognition_source_provider=provider), actor

    @app.post("/api/projectone/finance/performance-obligations")
    def projectone_performance_obligation_create(request: Request, body: dict = Body(default={})):
        data = body or {}
        def command():
            service, actor = _projectone_finance_commands(request)
            key = request.headers.get("Idempotency-Key")
            return service.create_performance_obligation(actor, data, idempotency_key=key)
        return run(request, command)

    @app.post("/api/projectone/finance/performance-obligations/{name}/workflow/{action}")
    def projectone_performance_obligation_workflow(request: Request, name: str, action: str,
                                                   body: dict = Body(default={})):
        data = body or {}
        def command():
            service, actor = _projectone_finance_commands(request)
            return service.workflow_action(actor, "Project Performance Obligation", name,
                                           action, data.get("evidence", {}))
        return run(request, command)

    @app.post("/api/projectone/finance/revenue-recognition/proposals")
    def projectone_revenue_recognition_proposal_create(request: Request, body: dict = Body(default={})):
        data = body or {}
        def command():
            service, actor = _projectone_finance_commands(request)
            try:
                return service.create_recognition_proposal(actor,
                    obligation_name=data.get("obligation_name"), period_end=data.get("period_end"),
                    idempotency_key=request.headers.get("Idempotency-Key"))
            except (RuntimeError, TypeError) as exc:           # a missing finance source or a malformed provider answer is a set-up problem the caller can read, not a server fault
                from velora.exceptions import ValidationError
                raise ValidationError(str(exc)) from None
        return run(request, command)

    @app.post("/api/projectone/finance/revenue-recognition/{name}/workflow/{action}")
    def projectone_revenue_recognition_workflow(request: Request, name: str, action: str,
                                                 body: dict = Body(default={})):
        data = body or {}
        def command():
            service, actor = _projectone_finance_commands(request)
            return service.workflow_action(actor, "Project Revenue Recognition", name,
                                           action, data.get("evidence", {}))
        return run(request, command)

    @app.post("/api/projectone/finance/earned-value/calculate")
    def projectone_earned_value_calculate(request: Request, body: dict = Body(default={})):
        return run(request, lambda: calculate_earned_value(**(body or {})))

    @app.post("/api/projectone/finance/portfolio-rollup")
    def projectone_portfolio_financial_rollup(request: Request, body: dict = Body(default={})):
        return run(request, lambda: portfolio_financial_rollup((body or {}).get("project_positions", [])))

    @app.post("/api/projectone/controls/risk-assessment")
    def projectone_assess_risk(request: Request, body: dict = Body(default={})):
        return run(request, lambda: assess_risk(body or {}))

    @app.post("/api/projectone/controls/change-request/validate")
    def projectone_validate_change(request: Request, body: dict = Body(default={})):
        return run(request, lambda: {"valid": validate_change_request(body or {})})

    @app.post("/api/projectone/controls/quality-gate")
    def projectone_quality_gate(request: Request, body: dict = Body(default={})):
        return run(request, lambda: quality_gate(body or {}))

    @app.post("/api/projectone/dashboards/suite")
    def projectone_dashboard_suite(request: Request, body: dict = Body(default={})):
        # Host adapter must permission-filter every collection before this projection.
        def build():
            data = dict(body or {})
            filters = data.pop("filters", {})
            return build_dashboard_suite(filter_dashboard_data(data, filters))
        return run(request, build)

    @app.post("/api/projectone/dashboards/{dashboard_name}")
    def projectone_dashboard(request: Request, dashboard_name: str, body: dict = Body(default={})):
        def build():
            builder = DASHBOARDS.get(dashboard_name)
            if builder is None:
                raise ValueError("Unknown dashboard.")
            data = dict(body or {})
            filters = data.pop("filters", {})
            return builder(filter_dashboard_data(data, filters))
        return run(request, build)

    @app.post("/api/projectone/dashboards/{dashboard_name}/drilldown")
    def projectone_dashboard_drilldown(request: Request, dashboard_name: str, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: dashboard_drilldown(data.get("data", {}), dashboard_name,
            data.get("collection"), data.get("filters"), data.get("limit", 100), data.get("offset", 0)))

    @app.post("/api/projectone/dashboards/trends/monthly")
    def projectone_dashboard_trends(request: Request, body: dict = Body(default={})):
        data = body or {}
        return run(request, lambda: trend_series(data.get("rows", []), date_field=data.get("date_field", "posting_date"),
            value_field=data.get("value_field", "amount"), currency_field=data.get("currency_field", "currency")))

    @app.post("/api/projectone/dashboards/views/validate")
    def projectone_dashboard_view_validate(request: Request, body: dict = Body(default={})):
        return run(request, lambda: validate_dashboard_view(body or {}))

    @app.post("/api/projectone/dashboards/snapshots/preview")
    def projectone_dashboard_snapshot_preview(request: Request, body: dict = Body(default={})):
        data = body or {}
        # company_scope must be injected by the trusted host adapter, never a browser field.
        trusted_scope = getattr(request.state, "company_scope", None)
        if not trusted_scope:
            return run(request, lambda: (_ for _ in ()).throw(ValueError("Trusted company scope is required from the host.")))
        return run(request, lambda: build_dashboard_snapshot(data.get("dashboard"), data.get("payload"),
            generated_at=data.get("generated_at"), company_scope=trusted_scope))

    @app.post("/api/projectone/reports/executive-dashboard")
    def projectone_executive_dashboard(request: Request, body: dict = Body(default={})):
        return run(request, lambda: executive_dashboard((body or {}).get("projects", [])))

    @app.post("/api/projectone/ai/project-insights")
    def projectone_project_insights(request: Request, body: dict = Body(default={})):
        return run(request, lambda: project_insights(body or {}))


    @app.post("/api/projectone/timesheets/validate")
    def projectone_validate_timesheet(request: Request, body: dict = Body(default={})):
        return run(request, lambda: validate_resource_timesheet(body or {}))

    # Approved-hours extraction and Payroll hand-off are performed only by the
    # authenticated host workflow/integration adapter against persisted approvals.


    # Enterprise capacity is a read-only, company-scoped portfolio projection.
    @app.get("/api/projectone/capacity/enterprise")
    def projectone_enterprise_capacity(request: Request, start_date: str | None = None, end_date: str | None = None):
        def build():
            from datetime import date, timedelta
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            from velora_projectone.projectone.services.enterprise_capacity import build_enterprise_capacity
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            bridge.assert_permission(actor, "projectone.portfolio.read")
            repo = bridge.document_repository()
            start = start_date or date.today().isoformat()
            end = end_date or (date.fromisoformat(start) + timedelta(days=30)).isoformat()
            def all_rows(doctype):
                rows = []
                for offset in range(0, 5000, 500):
                    batch = repo.list(actor, doctype, limit=500, offset=offset)
                    rows.extend(batch)
                    if len(batch) < 500: break
                if len(rows) >= 5000:
                    raise ValueError(f"{doctype} exceeds the 5,000-row capacity projection safety limit.")
                return rows
            profiles = all_rows("Resource Profile")
            tasks = all_rows("Project Task")
            allocations = all_rows("Project Resource Allocation")
            calendars = all_rows("Resource Calendar")
            exceptions = all_rows("Resource Availability Exception")
            result = build_enterprise_capacity(profiles, tasks, allocations, calendars, exceptions,
                                               start_date=start, end_date=end)
            result["metadata"].update({"company_scope": actor.company_id, "task_rows": len(tasks),
                                      "resource_rows": len(profiles), "portfolio_permission_required": True})
            return result
        return run(request, build)

    @app.get("/api/projectone/capacity/forecast")
    def projectone_capacity_forecast(request: Request, start_date: str | None = None,
                                     end_date: str | None = None, bucket: str = "week"):
        def build():
            from datetime import date, timedelta
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            from velora_projectone.projectone.services.enterprise_capacity import build_enterprise_capacity
            from velora_projectone.projectone.services.resource_levelling import build_workload_forecast
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            bridge.assert_permission(actor, "projectone.portfolio.read")
            repo = bridge.document_repository()
            start = start_date or date.today().isoformat()
            end = end_date or (date.fromisoformat(start) + timedelta(days=90)).isoformat()
            def rows(doctype):
                result = []
                for offset in range(0, 5000, 500):
                    batch = repo.list(actor, doctype, limit=500, offset=offset)
                    result.extend(batch)
                    if len(batch) < 500: break
                if len(result) >= 5000:
                    raise ValueError(f"{doctype} exceeds the 5,000-row forecast safety limit.")
                return result
            projection = build_enterprise_capacity(rows("Resource Profile"), rows("Project Task"),
                rows("Project Resource Allocation"), rows("Resource Calendar"),
                rows("Resource Availability Exception"), start_date=start, end_date=end)
            forecast = build_workload_forecast(projection["daily_capacity"], bucket=bucket)
            forecast.update({"period": projection["period"], "company_scope": actor.company_id,
                             "portfolio_permission_required": True, "source_projection": "tenant_scoped_native_read_model"})
            return forecast
        return run(request, build)

    @app.post("/api/projectone/capacity/levelling-preview")
    def projectone_capacity_levelling_preview(request: Request, body: dict = Body(default={} )):
        def build():
            from datetime import date, timedelta
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            from velora_projectone.projectone.services.enterprise_capacity import build_enterprise_capacity
            from velora_projectone.projectone.services.resource_levelling import preview_resource_levelling
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            bridge.assert_permission(actor, "projectone.portfolio.read")
            repo = bridge.document_repository(); data = body or {}
            start = data.get("start_date") or date.today().isoformat()
            end = data.get("end_date") or (date.fromisoformat(start) + timedelta(days=30)).isoformat()
            def rows(doctype):
                result = []
                for offset in range(0, 5000, 500):
                    batch = repo.list(actor, doctype, limit=500, offset=offset)
                    result.extend(batch)
                    if len(batch) < 500: break
                if len(result) >= 5000:
                    raise ValueError(f"{doctype} exceeds the 5,000-row levelling safety limit.")
                return result
            profiles, tasks = rows("Resource Profile"), rows("Project Task")
            projection = build_enterprise_capacity(profiles, tasks, rows("Project Resource Allocation"),
                rows("Resource Calendar"), rows("Resource Availability Exception"),
                start_date=start, end_date=end)
            result = preview_resource_levelling(tasks, profiles, projection["daily_capacity"])
            result.update({"period": projection["period"], "company_scope": actor.company_id,
                           "portfolio_permission_required": True, "source_projection": "tenant_scoped_native_read_model"})
            return result
        return run(request, build)

    @app.get("/api/projectone/workbench/projects/{project_id}/escalations")
    def projectone_project_escalations(request: Request, project_id: str, as_of: str | None = None, due_soon_days: int = 3):
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            from velora_projectone.projectone.services.enterprise_capacity import build_escalation_register
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            bridge.assert_permission(actor, "projectone.project.read", project_id=project_id)
            repo = bridge.document_repository()
            if not repo.get(actor, "Project", project_id): raise KeyError(project_id)
            tasks = repo.list(actor, "Project Task", filters={"project": project_id}, limit=500)
            result = build_escalation_register(tasks, as_of=as_of, due_soon_days=due_soon_days)
            result["metadata"] = {"project": project_id, "notification_adapter": "not_connected_or_not_invoked",
                                  "notification_delivery": False}
            return result
        return run(request, build)

    # Project Manager Workbench: all rows are loaded from the authenticated,
    # tenant-scoped native repository. The projection itself is read-only.
    @app.get("/api/projectone/workbench/projects/{project_id}")
    def projectone_workbench(request: Request, project_id: str, as_of: str | None = None,
                             assignee: str | None = None, priority: str | None = None):
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            from velora_projectone.projectone.services.workbench import build_task_board, resource_capacity_warnings
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            bridge.assert_permission(actor, "projectone.project.read", project_id=project_id)
            repo = bridge.document_repository()
            project = repo.get(actor, "Project", project_id)
            if not project:
                raise KeyError(project_id)
            tasks = repo.list(actor, "Project Task", filters={"project": project_id}, limit=500)
            allocations = repo.list(actor, "Project Resource Allocation", filters={"project": project_id}, limit=500)
            board = build_task_board(tasks, as_of=as_of, assignee=assignee, priority=priority)
            board["resource_capacity_warnings"] = resource_capacity_warnings(tasks, allocations)
            board["project"] = {"name": project.get("name"), "title": project.get("project_name") or project.get("title") or project_id}
            board["metadata"] = {"source": "native_velora_documents", "read_only_projection": True,
                                  "resource_warnings_are_advisory": True}
            return board
        return run(request, build)

    @app.post("/api/projectone/tasks/{task_id}/workflow/{action}")
    def projectone_task_workflow(request: Request, task_id: str, action: str, body: dict = Body(default={} )):
        data = body or {}
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            if set(data) - {"evidence"}:
                raise ValueError("Only workflow evidence may be supplied; identity and state are host controlled.")
            return bridge.workflow_action(actor, "Project Task", task_id, action, data.get("evidence") or {})
        return run(request, build)

    @app.post("/api/projectone/tasks/{task_id}/reassign")
    def projectone_task_reassign(request: Request, task_id: str, body: dict = Body(default={} )):
        data = body or {}
        def build():
            from copy import deepcopy
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            if set(data) - {"assignee", "team", "expected_version"}:
                raise ValueError("Only assignee, team and expected_version are accepted.")
            expected = data.get("expected_version")
            if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
                raise ValueError("A positive expected_version is required.")
            repo = bridge.document_repository(); before = repo.get(actor, "Project Task", task_id)
            if not before:
                raise KeyError(task_id)
            project_id = before.get("project")
            bridge.assert_permission(actor, "projectone.task.assign", project_id=project_id)
            allowed = {k: data[k] for k in ("assignee", "team") if k in data}
            if not allowed:
                raise ValueError("At least one assignment field is required.")
            if before.get("version") != expected:
                from velora_projectone.projectone.services.persistence import VersionConflict
                raise VersionConflict("Task changed; reload before reassignment.")
            with bridge.transaction_manager.transaction() as session:
                current = bridge.document_engine.get(session, "Project Task", task_id, actor.company_id)
                if not current or current.get("project") != project_id:
                    raise KeyError(task_id)
                if current.get("version") != expected:
                    from velora_projectone.projectone.services.persistence import VersionConflict
                    raise VersionConflict("Task changed; reload before reassignment.")
                saved = bridge.document_engine.update_if_version(session, "Project Task", task_id,
                    actor.company_id, allowed, expected, actor.actor_id)
                bridge.audit_service.append(session, company_id=actor.company_id, project_id=project_id,
                    actor_id=actor.actor_id, action="project_task.reassigned", before=before, after=saved)
            return {"task": saved, "audit": "appended", "authority": "Velora native document engine"}
        return run(request, build)

    @app.get("/api/projectone/workflow/inbox")
    def projectone_workflow_inbox(request: Request, limit: int = 100):
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            return {"items": bridge.pending_workflow_items(actor, limit=limit),
                    "authority": "Velora host workflow adapter"}
        return run(request, build)

    @app.post("/api/projectone/tasks/{task_id}/comments")
    def projectone_task_comment(request: Request, task_id: str, body: dict = Body(default={} )):
        data = body or {}
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            if set(data) != {"comment"} or not isinstance(data.get("comment"), str):
                raise ValueError("A comment string is required; identity and timestamp are host controlled.")
            comment = data["comment"].strip()
            if not comment or len(comment) > 4000:
                raise ValueError("Comment must contain 1 to 4000 characters.")
            task = bridge.document_repository().get(actor, "Project Task", task_id)
            if not task:
                raise KeyError(task_id)
            project_id = task.get("project")
            bridge.assert_permission(actor, "projectone.task.comment", project_id=project_id)
            with bridge.transaction_manager.transaction() as session:
                bridge.audit_service.append(session, company_id=actor.company_id, project_id=project_id,
                    actor_id=actor.actor_id, action="project_task.comment_added", before=None,
                    after={"task": task_id, "comment": comment})
            return {"task": task_id, "comment_recorded": True, "storage": "append_only_project_audit"}
        return run(request, build)

    @app.get("/api/projectone/projects/{project_id}/collaboration-feed")
    def projectone_project_collaboration_feed(request: Request, project_id: str, limit: int = 100):
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
                raise ValueError("limit must be between 1 and 500.")
            project = bridge.document_repository().get(actor, "Project", project_id)
            if not project:
                raise KeyError(project_id)
            events = bridge.audit_events(actor, project_id, limit=limit)
            return {"project": project_id, "events": events, "count": len(events),
                    "source": "append_only_project_audit", "read_only": True,
                    "company_scope": actor.company_id}
        return run(request, build)

    @app.get("/api/projectone/tasks/{task_id}/activity")
    def projectone_task_activity(request: Request, task_id: str, limit: int = 100):
        def build():
            from velora_projectone.projectone.integrations.native_bridge import native_integration_registry
            from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
            bridge = native_integration_registry.get(); actor = getattr(request.state, "projectone_actor", None)
            if bridge is None or not isinstance(actor, AuthenticatedActor):
                raise PermissionError("Configured native integration and authenticated actor are required.")
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
                raise ValueError("limit must be between 1 and 200.")
            task = bridge.document_repository().get(actor, "Project Task", task_id)
            if not task:
                raise KeyError(task_id)
            project_id = task.get("project")
            bridge.assert_permission(actor, "projectone.task.read", project_id=project_id)
            events = bridge.audit_service.list_for_project(project_id, actor.company_id, limit=limit)
            selected = [event for event in events if (event.get("after") or {}).get("task") == task_id
                        or event.get("action", "").startswith("project_task.") and
                        ((event.get("after") or {}).get("name") == task_id or (event.get("before") or {}).get("name") == task_id)]
            return {"task": task_id, "events": selected[:limit], "source": "append_only_project_audit"}
        return run(request, build)
