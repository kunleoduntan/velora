from decimal import Decimal
from velora import get_list, get_doc
from velora.reporting import Column, ReportBuilder
from velora.permissions import check_permission
from velora.meta.registry import registry
from velora_erp.finance.credit_control import customer_credit_exposure, receivables_exposure, open_order_commitment

def execute(filters):
    filters=filters or {}
    check_permission(registry.get("Customer"), "read")
    customers=get_list("Customer",fields=["name","customer_name","credit_limit","credit_hold","credit_hold_reason"],limit=5000,ignore_permissions=True)
    rb=ReportBuilder("Customer Credit Exposure",[Column("customer","Customer","Link"),Column("customer_name","Customer Name","Data"),Column("receivables","Receivables","Currency"),Column("order_commitment","Open Order Commitment","Currency"),Column("total_exposure","Total Exposure","Currency"),Column("credit_limit","Credit Limit","Currency"),Column("available_credit","Available Credit","Currency"),Column("credit_status","Credit Status","Data"),Column("credit_hold_reason","Credit Hold Reason","Data")])
    for c in customers:
        if filters.get("customer") and c["name"]!=filters["customer"]: continue
        ar=receivables_exposure(c["name"])
        commitment=open_order_commitment(c["name"]) if bool(filters.get("include_open_orders",1)) else Decimal("0")
        total=max(Decimal("0"),ar+commitment)
        limit=Decimal(str(c.get("credit_limit") or 0)); available=None if limit==0 else limit-total
        status="On Hold" if c.get("credit_hold") else ("Over Limit" if limit>0 and total>limit else ("Within Limit" if limit>0 else "Unlimited"))
        if filters.get("only_over_limit") and status not in ("Over Limit","On Hold"): continue
        rb.row({"customer":c["name"],"customer_name":c.get("customer_name"),"receivables":ar,"order_commitment":commitment,"total_exposure":total,"credit_limit":limit,"available_credit":available,"credit_status":status,"credit_hold_reason":c.get("credit_hold_reason")})
    return rb.build(filters=[("Customer",filters.get("customer") or "All"),("Include Open Orders",bool(filters.get("include_open_orders",1)))])
