"""Velora ProjectOne application lifecycle and provider declarations."""
app_title = "Velora ProjectOne"
app_description = "Enterprise project, programme and portfolio management."
app_guide = "docs/PROJECTONE-GUIDE-v*.html"
required_apps = ["velora_erp"]
required_velora = ">=1.16.2,<1.20.0"
required_packages = []
after_install = "velora_projectone.setup.after_install"
after_migrate = "velora_projectone.setup.after_migrate"
api_routes_provider = "velora_projectone.api_routes"
frontend_assets = ["frontend/projectone-forms.js", "frontend/projectone-agile.js", "frontend/projectone-resources.js", "frontend/projectone-finance.js", "frontend/projectone-dashboards.js", "frontend/projectone-executive.js", "frontend/projectone-schedule.js", "frontend/projectone-workbench.js", "frontend/projectone-capacity.js", "frontend/projectone-programme-intelligence.js", "frontend/projectone.css"]
# ProjectOne intentionally does not register accounting posting hooks.
doc_events = {}
