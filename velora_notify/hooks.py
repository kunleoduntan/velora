app_name = "velora_notify"
app_title = "Notifications"
app_description = "Rules, channels, an outbox with retries, preferences, digests and escalation"
required_apps = []
required_velora = ">=0.8"
required_packages = []
after_install = None
before_uninstall = None

# one handler per event (a handler receives only the document)
doc_events = {"*": {"after_insert": "velora_notify.engine.on_after_insert", "on_update": "velora_notify.engine.on_update",
                    "on_submit": "velora_notify.engine.on_submit", "on_cancel": "velora_notify.engine.on_cancel"}}
scheduler_events = {"every_tick": ["velora_notify.jobs.deliver", "velora_notify.jobs.deliver_integrations"], "every_minute": ["velora_notify.jobs.maintain", "velora_notify.jobs.maintain_integrations", "velora_notify.broadcast.jobs.tick"], "daily": ["velora_notify.jobs.scan_dates"]}

api_routes_provider = "velora_notify.api_routes"
