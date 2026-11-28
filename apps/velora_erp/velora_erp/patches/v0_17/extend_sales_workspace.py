from velora.application_workspaces import listing, save


def execute():
    existing = listing()
    current = next((row for row in existing if row.get("scope") == "company" and row.get("name") == "Sales"), None)
    widgets = list((current or {}).get("layout") or [])
    additions = [
        {"type": "shortcut", "title": "Sales Quotations", "description": "Prepare, approve and track customer quotations", "route": "#/app/Sales Quotation", "width": 2},
        {"type": "shortcut", "title": "Sales Quotation Register", "description": "Monitor quotation validity, approval and conversion", "route": "#/report/Sales Quotation Register", "width": 2},
    ]
    titles = {widget.get("title") for widget in widgets}
    widgets.extend(widget for widget in additions if widget["title"] not in titles)
    save({"id": (current or {}).get("id"), "name": "Sales",
          "description": "Customer quotations, orders, deliveries, invoicing and receipts.",
          "visibility": "company", "roles": [], "widgets": widgets}, "company")
