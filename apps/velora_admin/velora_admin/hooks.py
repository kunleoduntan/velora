app_title = "Velora Admin"
app_description = "Administrative management application for the Velora platform."
app_guide = "docs/VELORA-ADMIN-GUIDE-v*.html"
required_apps = ["velora_erp"]
required_velora = ">=1.16.2,<1.20.0"
required_packages = []
api_routes_provider = "velora_admin.api_routes"
scheduler_events = {"daily": ["velora_admin.administration.service_operations.daily_service_maintenance", "velora_admin.administration.universal_admin.run_daily_admin_automation", "velora_admin.administration.renewal_management.daily_renewal_scan"]}
