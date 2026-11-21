"""Landed-cost allocation calculations; stock valuation posting is a later integration."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from velora import get_doc, throw

def _dec(v,label):
    try: x=Decimal(str(v or 0))
    except (InvalidOperation,TypeError,ValueError): throw(f"{label} must be numeric.")
    if not x.is_finite() or x<0: throw(f"{label} must be a finite non-negative amount.")
    return x

def calculate_allocations(total, rows, method, precision=2):
    total=_dec(total,"Total landed cost")
    if not rows: throw("At least one inventory allocation line is required.")
    basis={"By Value":"item_value","By Quantity":"quantity","By Weight":"weight","By Volume":"volume","Equal":None}.get(method,"invalid")
    if basis=="invalid": throw("Unsupported landed cost allocation method.")
    weights=[]
    for r in rows:
        w=Decimal("1") if basis is None else _dec(r.get(basis),basis.replace("_"," ").title())
        weights.append(w)
    denom=sum(weights,Decimal("0"))
    if denom<=0: throw("The selected allocation basis must have a positive total.")
    quantum=Decimal("1").scaleb(-precision); result=[]; assigned=Decimal("0")
    for idx,w in enumerate(weights):
        value=(total-assigned) if idx==len(weights)-1 else (total*w/denom).quantize(quantum,rounding=ROUND_HALF_UP)
        assigned+=value; result.append(value)
    return result

def validate_landed_cost_voucher(doc):
    if not doc.voucher_date or not doc.purchase_receipt: throw("Voucher Date and Purchase Receipt are required.")
    receipt=get_doc("Purchase Receipt",doc.purchase_receipt)
    if int(receipt.docstatus or 0)!=1: throw("Landed costs can only be applied to a submitted Purchase Receipt.")
    if not receipt.warehouse: throw("The linked Purchase Receipt must have a receiving Warehouse before landed cost can be capitalised.")
    doc.supplier=receipt.party; doc.currency=doc.currency or receipt.currency
    if doc.currency!=receipt.currency: throw("Landed Cost Voucher currency must match the Purchase Receipt currency.")
    if _dec(doc.exchange_rate, "Exchange Rate") <= 0: throw("Exchange Rate must be greater than zero.")
    if not doc.charges or not doc.allocations: throw("Enter landed cost charges and item allocation lines.")
    total=Decimal("0")
    for index, charge in enumerate(doc.charges,1):
        amount=_dec(charge.amount,f"Charge {index} Amount")
        if amount<=0: throw(f"Charge {index}: amount must be greater than zero.")
        account=get_doc("Account",charge.charge_account)
        if getattr(account,"disabled",0): throw(f"Charge {index}: select an active charge account.")
        if getattr(account,"root_type",None)!="Expense": throw(f"Charge {index}: landed cost charge account must be an Expense account or clearing account classified under Expense.")
        total+=amount
    if total<=0: throw("Total landed cost must be greater than zero.")
    receipt_lines={str(getattr(x,"name","")):x for x in receipt.lines or []}
    seen=set()
    for index, allocation in enumerate(doc.allocations,1):
        key=str(allocation.source_line or "")
        original=receipt_lines.get(key)
        if not original: throw(f"Allocation {index}: select a line from the linked Purchase Receipt.")
        if key in seen: throw(f"Allocation {index}: a Purchase Receipt line can only be allocated once.")
        seen.add(key)
        if allocation.item_code and allocation.item_code != original.item_code: throw(f"Allocation {index}: Item Code does not match the Purchase Receipt line.")
        allocation.item_code=original.item_code
        allocation.description=allocation.description or original.description
        factor=_dec(getattr(original,"conversion_factor",1) or 1,"Receipt conversion factor")
        if factor<=0: throw(f"Allocation {index}: Stock UOM Conversion Factor must be greater than zero.")
        # Quantity allocation is based on stock units, not the supplier's pack UOM.
        allocation.quantity=_dec(original.quantity,"Receipt quantity")*factor
        if not _dec(getattr(allocation,"item_value",0),"Item value"):
            allocation.item_value=_dec(original.quantity,"Receipt quantity")*_dec(getattr(original,"valuation_rate",0),"Receipt valuation rate")*_dec(getattr(receipt,"exchange_rate",1) or 1,"Receipt exchange rate")
    values=calculate_allocations(total,[{"quantity":x.quantity,"item_value":x.item_value,"weight":x.weight,"volume":x.volume} for x in doc.allocations],doc.allocation_method or "By Value")
    for line,value in zip(doc.allocations,values): line.allocated_amount=value
    doc.total_charges=total; doc.allocated_total=sum(values,Decimal("0")); doc.allocation_status="Balanced" if doc.allocated_total==total else "Unbalanced"
    if doc.allocated_total!=total: throw("Allocated landed cost must equal total charges exactly.")
