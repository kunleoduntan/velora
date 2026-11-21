from velora.application_workspaces import listing, save


def execute():
    current = next((row for row in listing() if row.get("scope") == "company" and row.get("name") == "Sales"), None)
    widgets = list((current or {}).get("layout") or [])
    additions = [
        {"type": "shortcut", "title": "Customer Credit Exposure", "description": "Review receivables, open orders and available customer credit", "route": "#/report/Customer Credit Exposure", "width": 2},
        {"type": "shortcut", "title": "Customer Complaints", "description": "Register, assign and resolve customer complaints", "route": "#/app/Customer Complaint", "width": 2},
        {"type": "shortcut", "title": "Customer Complaint Register", "description": "Monitor complaint severity, ownership and resolution status", "route": "#/report/Customer Complaint Register", "width": 2},
    ]
    titles = {widget.get("title") for widget in widgets}
    widgets.extend(widget for widget in additions if widget["title"] not in titles)
    save({"id": (current or {}).get("id"), "name": "Sales",
          "description": "Customer quotations, orders, deliveries, invoicing, credit control, returns and service." ,
          "visibility": "company", "roles": [], "widgets": widgets}, "company")
