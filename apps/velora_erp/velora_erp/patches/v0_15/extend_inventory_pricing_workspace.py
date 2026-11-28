from velora.application_workspaces import listing, save


def execute():
    from velora_erp.finance.pricing import refresh_all_last_purchase_costs
    refresh_all_last_purchase_costs()
    existing = listing()
    current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == "Inventory"), None)
    widgets = list((current or {}).get("layout") or [])
    additions = [
        {"type": "shortcut", "title": "Inventory Items", "description": "Maintain stock items, valuation and selling-price policies", "route": "#/app/Inventory Item", "width": 2},
        {"type": "shortcut", "title": "Customer Groups", "description": "Configure inherited customer selling margins", "route": "#/app/Customer Group", "width": 2},
        {"type": "shortcut", "title": "Inventory Settings", "description": "Configure cost-based pricing and below-cost controls", "route": "#/app/Inventory Settings", "width": 2},
    ]
    titles = {widget.get("title") for widget in widgets}
    widgets.extend(widget for widget in additions if widget["title"] not in titles)
    save({"id": (current or {}).get("id"), "name": "Inventory",
          "description": "Stock control, valuation, traceability and cost-protected selling prices.",
          "visibility": "company", "roles": [], "widgets": widgets}, "company")
