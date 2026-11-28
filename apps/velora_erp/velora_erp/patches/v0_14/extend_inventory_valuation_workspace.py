from velora.application_workspaces import listing, save


def execute():
    existing = listing()
    current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == "Inventory"), None)
    widgets = list((current or {}).get("layout") or [])
    additions = [
        {"type": "shortcut", "title": "Opening Stock Entries", "description": "Import approved opening inventory quantities and values", "route": "#/app/Opening Stock Entry", "width": 2},
        {"type": "shortcut", "title": "Stock Revaluation", "description": "Revalue existing stock without changing quantities", "route": "#/app/Stock Revaluation", "width": 2},
        {"type": "shortcut", "title": "Inventory Valuation Closing", "description": "Finalise periodic weighted average valuation", "route": "#/app/Inventory Valuation Closing", "width": 2},
    ]
    titles = {widget.get("title") for widget in widgets}
    widgets.extend(widget for widget in additions if widget["title"] not in titles)
    save({"id": (current or {}).get("id"), "name": "Inventory",
          "description": "Stock control, FIFO, moving average, periodic weighted average, reconciliation and traceability.",
          "visibility": "company", "roles": [], "widgets": widgets}, "company")
