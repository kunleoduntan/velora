from velora.application_workspaces import listing, save

def execute():
    existing = listing()
    current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == "Inventory"), None)
    widgets = list((current or {}).get("layout") or [])
    shortcuts = [
        {"type":"shortcut","title":"Inventory Items","description":"Maintain stock item masters and tracking settings","route":"#/app/Inventory Item","width":2},
        {"type":"shortcut","title":"Warehouses","description":"Maintain inventory locations","route":"#/app/Warehouse","width":2},
        {"type":"shortcut","title":"Stock Reconciliation","description":"Count physical stock and generate controlled adjustments","route":"#/app/Stock Reconciliation","width":2},
        {"type":"shortcut","title":"Stock Ledger","description":"Review immutable stock quantity and valuation history","route":"#/app/Stock Ledger Record","width":2},
        {"type":"shortcut","title":"Serial Numbers","description":"Trace serialized inventory","route":"#/app/Serial Number","width":2},
        {"type":"shortcut","title":"Batches","description":"Trace batch-controlled inventory","route":"#/app/Batch","width":2},
        {"type":"shortcut","title":"Inventory Settings","description":"Configure inventory valuation and accounting accounts","route":"#/app/Inventory Settings","width":2},
        {"type":"shortcut","title":"Landed Cost Vouchers","description":"Capitalise acquisition costs into inventory valuation","route":"#/app/Landed Cost Voucher","width":2},
    ]
    titles = {widget.get("title") for widget in widgets}
    widgets.extend(widget for widget in shortcuts if widget["title"] not in titles)
    save({"id":(current or {}).get("id"),"name":"Inventory","description":"Stock control, valuation, reconciliation and traceability.","visibility":"company","roles":[],"widgets":widgets},"company")
