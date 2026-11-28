app_name = "velora_governance"
app_title = "Velora Governance"
app_description = "Corporate governance, board management, corporate secretarial, compliance and sustainability reporting."
required_apps = []
required_velora = ">=1.16.2,<1.20.0"
required_packages = []
before_install = None
after_install = "velora_governance.setup.after_install"
before_uninstall = None
after_uninstall = None
before_migrate = None
after_migrate = "velora_governance.setup.after_migrate"
frontend_assets = []
api_routes_provider = "velora_governance.api_routes"
doc_events = {
    "Board Action": {"on_update": "velora_governance.governance.services.governance_automation_event_trigger.on_source_update"},
    "Governance Obligation": {"on_update": "velora_governance.governance.services.governance_automation_event_trigger.on_source_update"},
    "Corporate Filing": {"on_update": "velora_governance.governance.services.governance_automation_event_trigger.on_source_update"},
    "Annual Return": {"on_update": "velora_governance.governance.services.governance_automation_event_trigger.on_source_update"},
    "Regulatory Correspondence": {"on_update": "velora_governance.governance.services.governance_automation_event_trigger.on_source_update"},
    "Sustainability Data Collection Task": {"on_update": "velora_governance.governance.services.governance_automation_event_trigger.on_source_update"},
}
scheduler_events = {
    "daily": [
        "velora_governance.jobs.daily_governance_maintenance",
        "velora_governance.jobs.daily_generate_governance_automation",
    ],
    "hourly": ["velora_governance.jobs.hourly_execute_governance_automation",
        "velora_governance.jobs.hourly_governance_exception_escalations"],
}
job_handlers = {}
