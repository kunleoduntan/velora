from velora import get_list, throw
from velora.reporting import Column, ReportBuilder
from velora.permissions import check_permission
from velora.meta.registry import registry

def execute(filters):
    filters=filters or {}
    start=str(filters.get("from_date") or "").strip(); end=str(filters.get("to_date") or "").strip()
    if start and end and start>end: throw("From Date cannot be later than To Date.")
    check_permission(registry.get("Customer Complaint"),"read")
    rows=get_list("Customer Complaint",fields=["name","complaint_date","customer","sales_invoice","delivery_note","category","severity","assigned_to","resolution_status","resolved_on","related_return","related_replacement_order"],limit=5001,ignore_permissions=True)
    if len(rows)>5000: throw("More than 5,000 complaints were found. Apply narrower filters.")
    rb=ReportBuilder("Customer Complaint Register",[Column("complaint_date","Complaint Date","Date"),Column("complaint","Complaint","Link"),Column("customer","Customer","Link"),Column("sales_invoice","Sales Invoice","Link"),Column("delivery_note","Delivery Note","Link"),Column("category","Category","Data"),Column("severity","Severity","Data"),Column("assigned_to","Assigned To","Data"),Column("resolution_status","Status","Data"),Column("resolved_on","Resolved On","Date"),Column("related_return","Sales Return","Link"),Column("related_replacement_order","Replacement Sales Order","Link")])
    for r in rows:
        dt=str(r.get("complaint_date") or "")[:10]
        if start and dt<start: continue
        if end and dt>end: continue
        if filters.get("customer") and r.get("customer")!=filters["customer"]: continue
        if filters.get("resolution_status") and r.get("resolution_status")!=filters["resolution_status"]: continue
        if filters.get("severity") and r.get("severity")!=filters["severity"]: continue
        rb.row({"complaint_date":r.get("complaint_date"),"complaint":r.get("name"),**{k:r.get(k) for k in ("customer","sales_invoice","delivery_note","category","severity","assigned_to","resolution_status","resolved_on","related_return","related_replacement_order")}})
    return rb.build(filters=[("Customer",filters.get("customer") or "All"),("Status",filters.get("resolution_status") or "All"),("Severity",filters.get("severity") or "All"),("From Date",start or "All"),("To Date",end or "All")])
