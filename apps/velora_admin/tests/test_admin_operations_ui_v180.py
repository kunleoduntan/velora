from pathlib import Path

def test_v180_workbench_ui_has_six_domains_and_operational_forms():
    module_path = Path(__file__).parents[1] / "velora_admin" / "administration" / "operations_ui.py"
    source = module_path.read_text()
    for expected in [
        "Facilities & Maintenance", "Fleet & Transport", "Supplies & Inventory",
        "Correspondence & Records", "Events & Visitors", "Travel Management",
        "createWorkOrder", "completeWorkOrder", "loadFleetAlerts",
        "checkTripConflicts", "checkVenueConflicts", "searchKnowledge",
    ]:
        assert expected in source

def test_v180_workbench_uses_existing_universal_api_routes():
    module_path = Path(__file__).parents[1] / "velora_admin" / "administration" / "operations_ui.py"
    source = module_path.read_text()
    for route in [
        "/api/admin/universal/work-orders",
        "/api/admin/universal/fleet/alerts",
        "/api/admin/universal/fleet/trip-conflicts",
        "/api/admin/universal/events/venue-conflicts",
        "/api/admin/universal/knowledge/search",
    ]:
        assert route in source
