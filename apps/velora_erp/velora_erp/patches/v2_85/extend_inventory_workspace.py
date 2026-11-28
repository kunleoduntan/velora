from velora.application_workspaces import listing


def execute():
    from velora_erp.setup import _save_fitted
    current = next((row for row in listing() if row.get("scope") == "company" and row.get("name") == "Inventory"), None)
    widgets = list((current or {}).get("layout") or [])
    additions = [
        {"type": "shortcut", "title": "Requests for Quotation", "description": "Ask suppliers to quote", "route": "#/app/Request for Quotation", "width": 2},
        {"type": "shortcut", "title": "Supplier Quotations", "description": "Prices suppliers quoted", "route": "#/app/Supplier Quotation", "width": 2},
        {"type": "shortcut", "title": "Quality Inspections", "description": "Inspect goods received and delivered", "route": "#/app/Quality Inspection", "width": 2},
        {"type": "shortcut", "title": "Stock Reservations", "description": "Stock set aside for orders", "route": "#/app/Stock Reservation", "width": 2},
        {"type": "shortcut", "title": "Cycle Counts", "description": "Count a few items often", "route": "#/app/Cycle Count", "width": 2},
        {"type": "shortcut", "title": "Stock Transfer Receipts", "description": "Receive goods that were in transit", "route": "#/app/Stock Transfer Receipt", "width": 2},
        {"type": "shortcut", "title": "Goods in Transit", "description": "Stock on the way between warehouses", "route": "#/report/Goods in Transit", "width": 2},
        {"type": "shortcut", "title": "Stock Availability", "description": "On hand, reserved and available", "route": "#/report/Stock Availability", "width": 2},
        {"type": "shortcut", "title": "Batch Expiry", "description": "Batches expired or expiring soon", "route": "#/report/Batch Expiry", "width": 2},
    ]
    titles = {w.get("title") for w in widgets}
    widgets.extend(w for w in additions if w["title"] not in titles)
    _save_fitted({"id": (current or {}).get("id"), "name": "Inventory", "description": (current or {}).get("description") or "Stock control, valuation, traceability and cost-protected selling prices.",
                  "visibility": "company", "roles": (current or {}).get("roles") or [], "widgets": widgets}, "company")
