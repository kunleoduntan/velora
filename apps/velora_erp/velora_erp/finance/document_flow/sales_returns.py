"""Create controlled partial Sales Returns from submitted Sales Invoices."""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from velora import db, get_doc, get_list, new_doc, throw

def _d(value, label):
    try: result=Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError): throw(f"{label} must be numeric.")
    if not result.is_finite(): throw(f"{label} must be finite.")
    return result

def original_issue_rate(invoice, source):
    """Cost per line UOM, in document currency, at which the goods originally left stock.

    A return must restock at the cost the sale relieved, not at the item's standard rate, otherwise COGS is
    reversed by a different amount than it was charged. Delivery Note lines record the realised issue cost; an
    invoice that delivered the goods itself (Update Stock) records it on its own line."""
    own=_d(getattr(source,"valuation_rate",0) or 0,"Line valuation rate")
    order=getattr(invoice,"source_document",None) if getattr(invoice,"source_doctype",None)=="Sales Order" else None
    key=str(getattr(source,"source_line","") or "")
    cost=qty=Decimal("0")
    if order and key:
        for entry in get_list("Delivery Note",filters={"source_doctype":"Sales Order","source_document":order,"docstatus":1},fields=["name"],limit=5000,ignore_permissions=True):
            for line in get_doc("Delivery Note",entry["name"],ignore_permissions=True).lines or []:
                if str(getattr(line,"source_line","") or "")!=key: continue
                q=_d(getattr(line,"quantity",0),"Delivered quantity")*_d(getattr(line,"conversion_factor",1) or 1,"Delivery conversion factor")
                cost+=_d(getattr(line,"issue_cost_amount",0),"Issue cost amount"); qty+=q
    if qty>0 and cost>0:
        per_stock_unit=cost/qty
        factor=_d(getattr(source,"conversion_factor",1) or 1,"Conversion factor")
        fx=_d(getattr(invoice,"exchange_rate",1) or 1,"Exchange rate")
        return (per_stock_unit*factor/fx).quantize(Decimal("0.000001"))
    return own

def create_sales_return_from_invoice(invoice_name, quantities=None, overrides=None):
    quantities=quantities or {}; overrides=overrides or {}
    allowed={"return_date","posting_date","warehouse","narration","return_disposition"}
    invalid=set(overrides)-allowed
    if invalid: throw("Unsupported return conversion override(s): "+", ".join(sorted(invalid)))
    with db.transaction():
        invoice=get_doc("Sales Invoice",invoice_name); invoice._lock_and_check()
        if int(invoice.docstatus or 0)!=1: throw("Only a submitted Sales Invoice can be returned.")
        prior_qty={}; prior_amount={}; prior_tax={}
        returns=get_list("Sales Return",filters={"source_invoice":invoice_name},fields=["name","docstatus"],limit=5000,ignore_permissions=True)
        if len(returns)>=5000: throw("Return history exceeds the supported conversion scan; contact an administrator for a controlled reconciliation.")
        for entry in returns:
            if int(entry.get("docstatus") or 0)==2: continue
            doc=get_doc("Sales Return",entry["name"],ignore_permissions=True)
            for line in doc.lines or []:
                key=str(getattr(line,"source_line","") or "")
                prior_qty[key]=prior_qty.get(key,Decimal("0"))+_d(line.quantity,"Previously returned quantity")
                prior_amount[key]=prior_amount.get(key,Decimal("0"))+_d(line.amount,"Previously returned amount")
                prior_tax[key]=prior_tax.get(key,Decimal("0"))+_d(line.tax_amount,"Previously reversed tax")
        lines=[]
        for source in invoice.lines or []:
            key=str(getattr(source,"name","") or "")
            original_qty=_d(getattr(source,"quantity",0),"Invoiced quantity")
            if original_qty<=0: continue
            remaining=original_qty-prior_qty.get(key,Decimal("0"))
            if remaining<=0: continue
            qty=_d(quantities.get(key,remaining),"Return quantity")
            if qty<=0 or qty>remaining: throw(f"Invoice line {key}: return quantity must be positive and no greater than {remaining}.")
            ratio=qty/original_qty
            amount=(_d(source.amount,"Invoice line amount")*ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tax=(_d(getattr(source,"tax_amount",0),"Invoice tax")*ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            lines.append({"source_line":key,"item_code":getattr(source,"item_code",None),"description":getattr(source,"description","") or "Customer return",
                "quantity":qty,"uom":getattr(source,"uom",None),"account":source.account,"amount":amount,
                "tax_account":getattr(source,"tax_account",None),"tax_code":getattr(source,"tax_code",None),
                "tax_rate":getattr(source,"tax_rate",0) or 0,"tax_amount":tax,"cost_centre":getattr(source,"cost_centre",None),
                "batch":getattr(source,"batch",None),"serial_number":getattr(source,"serial_number",None),
                "valuation_rate":original_issue_rate(invoice,source),"conversion_factor":getattr(source,"conversion_factor",1) or 1})
        if not lines: throw("All invoiced quantities have been fully returned; no remaining quantity is available.")
        doc=new_doc("Sales Return",return_date=overrides.get("return_date") or date.today().isoformat(),
            posting_date=overrides.get("posting_date") or date.today().isoformat(),party=invoice.party,source_invoice=invoice.name,
            currency=invoice.currency,exchange_rate=invoice.exchange_rate,warehouse=overrides.get("warehouse"),
            return_disposition=overrides.get("return_disposition") or "Restock",
            narration=overrides.get("narration") or f"Sales Return created from Sales Invoice {invoice.name}",lines=lines)
        doc.insert()
        return doc
