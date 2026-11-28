from velora.application_workspaces import listing, save


def execute():
    existing = listing()
    current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == "Inventory"), None)
    widgets = list((current or {}).get("layout") or [])
    additions = [
        {"type":"shortcut","title":"Stock Transfers","description":"Move inventory between warehouses with carrying-cost preservation","route":"#/app/Stock Transfer","width":2},
        {"type":"shortcut","title":"Stock Balance","description":"Review on-hand quantities and inventory carrying values","route":"#/report/Stock Balance","width":2},
    ]
    titles = {widget.get("title") for widget in widgets}
    widgets.extend(widget for widget in additions if widget["title"] not in titles)
    save({"id":(current or {}).get("id"),"name":"Inventory","description":"Stock control, valuation, reconciliation, warehouse movements and traceability.","visibility":"company","roles":[],"widgets":widgets},"company")
