from velora.application_workspaces import listing


def execute():
    from velora_erp.setup import _save_fitted
    current = next((row for row in listing() if row.get("scope") == "company" and row.get("name") == "Inventory"), None)
    widgets = list((current or {}).get("layout") or [])
    additions = [
        {"type": "shortcut", "title": "Material Requests", "description": "Request stock to buy, move or issue", "route": "#/app/Material Request", "width": 2},
        {"type": "shortcut", "title": "Stock Entries", "description": "Receive, issue or scrap stock", "route": "#/app/Stock Entry", "width": 2},
        {"type": "shortcut", "title": "Item Groups", "description": "Classify items", "route": "#/app/Item Group", "width": 2},
        {"type": "shortcut", "title": "Units of Measure", "description": "Units used to stock, buy and sell", "route": "#/app/Unit of Measure", "width": 2},
        {"type": "shortcut", "title": "Reorder Status", "description": "Items at or below their reorder level", "route": "#/report/Reorder Status", "width": 2},
        {"type": "shortcut", "title": "Stock Ledger", "description": "Every stock movement with running balance", "route": "#/report/Stock Ledger", "width": 2},
        {"type": "shortcut", "title": "Stock Ageing", "description": "How long on-hand stock has been held", "route": "#/report/Stock Ageing", "width": 2},
    ]
    titles = {w.get("title") for w in widgets}
    widgets.extend(w for w in additions if w["title"] not in titles)
    _save_fitted({"id": (current or {}).get("id"), "name": "Inventory", "description": (current or {}).get("description") or "Stock control, valuation, traceability and cost-protected selling prices.",
                  "visibility": "company", "roles": (current or {}).get("roles") or [], "widgets": widgets}, "company")
