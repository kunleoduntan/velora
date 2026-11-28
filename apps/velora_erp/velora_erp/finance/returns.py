"""Sales and Purchase Return validation and financial reversal posting."""
from decimal import Decimal
from velora import get_doc, get_list, throw
from velora_erp.finance.validation import row
from velora_erp.finance.source_documents import decimal_amount, ensure_approved, finance_settings, persist_posting_batch_link
from velora_erp.finance.adapters import PostingInstruction, PostingLine, post_source_document

def _d(v): return Decimal(str(v or 0))

def validate_return(doc, kind):
    source_type = "Sales Invoice" if kind == "Sales" else "Purchase Invoice"
    party_type = "Customer" if kind == "Sales" else "Supplier"
    if not doc.return_date or not doc.posting_date or not doc.source_invoice or not doc.party:
        throw("Return Date, Posting Date, source invoice and party are required.")
    from velora_erp.finance.inventory.ledger import is_stock_item
    has_stock = any(is_stock_item(getattr(line, "item_code", None)) for line in doc.lines or [])
    if has_stock and not doc.warehouse:
        throw("Return Warehouse is required for stock-managed items.")
    if doc.warehouse:
        warehouse = get_doc("Warehouse", doc.warehouse)
        if warehouse.disabled or warehouse.is_group:
            throw("Select an active leaf Return Warehouse.")
    source = get_doc(source_type, doc.source_invoice)
    source._lock_and_check()
    if int(source.docstatus or 0) != 1: throw("The source invoice must be submitted.")
    if source.party != doc.party: throw("Return party must match the original invoice.")
    doc.currency = (doc.currency or source.currency or finance_settings()["base_currency"]).upper()
    if doc.currency != source.currency: throw("Return currency must match the original invoice currency.")
    if _d(doc.exchange_rate) <= 0: throw("Exchange Rate must be greater than zero.")
    if not doc.narration or not str(doc.narration).strip(): throw("A return reason/narration is required.")
    if not doc.lines: throw("At least one return line is required.")
    source_lines = {str(getattr(x,"name","")):x for x in source.lines or []}
    existing = get_list(doc.doctype, filters={"source_invoice":doc.source_invoice}, fields=["name","docstatus"], limit=1000, ignore_permissions=True)
    returned = {}
    returned_tax = {}
    returned_qty = {}
    for r in existing:
        if r["name"] == doc.name: continue
        prior = get_doc(doc.doctype,r["name"])
        if int(prior.docstatus or 0) == 2: continue
        for ln in prior.lines or []:
            returned[str(ln.source_line)] = returned.get(str(ln.source_line),Decimal("0")) + _d(ln.amount)
            returned_tax[str(ln.source_line)] = returned_tax.get(str(ln.source_line),Decimal("0")) + _d(ln.tax_amount)
            returned_qty[str(ln.source_line)] = returned_qty.get(str(ln.source_line),Decimal("0")) + _d(ln.quantity)
    net=tax=Decimal("0")
    current_amount={}; current_tax={}; current_qty={}
    for i,line in enumerate(doc.lines,1):
        key=str(line.source_line or "")
        original=source_lines.get(key)
        if not original: throw(f"Return line {i} must reference a line on the original invoice.")
        amount=decimal_amount(line.amount,f"Line {i} return amount")
        tax_amount=decimal_amount(line.tax_amount,f"Line {i} tax reversal")
        if amount <= 0: throw(f"Line {i}: return amount must be greater than zero.")
        if amount + returned.get(key,Decimal("0")) + current_amount.get(key,Decimal("0")) > _d(original.amount): throw(f"Line {i}: cumulative returns cannot exceed the original invoiced net amount.")
        qty = _d(line.quantity)
        original_qty = _d(getattr(original,"quantity",0))
        if original_qty > 0 and (qty <= 0 or qty + returned_qty.get(key,Decimal("0")) + current_qty.get(key,Decimal("0")) > original_qty): throw(f"Line {i}: cumulative returned quantity must be positive and cannot exceed the original invoiced quantity.")
        if tax_amount < 0 or tax_amount + returned_tax.get(key,Decimal("0")) + current_tax.get(key,Decimal("0")) > _d(original.tax_amount): throw(f"Line {i}: tax reversal cannot exceed the original line tax amount.")
        if line.account != original.account: throw(f"Line {i}: account must match the original invoice line.")
        if (line.item_code or None) != (getattr(original,"item_code",None) or None): throw(f"Line {i}: Item Code must match the original invoice line.")
        if _d(line.tax_rate) != _d(getattr(original,"tax_rate",0)): throw(f"Line {i}: Tax Rate must match the original invoice line.")
        if (line.tax_code or None) != (getattr(original,"tax_code",None) or None): throw(f"Line {i}: Tax Code must match the original invoice line.")
        if (line.tax_account or None) != (getattr(original,"tax_account",None) or None): throw(f"Line {i}: tax account must match the original invoice line.")
        if tax_amount and not line.tax_account: throw(f"Line {i}: Tax Account is required for a tax reversal.")
        line.description = line.description or original.description
        line.tax_code = line.tax_code or getattr(original,"tax_code",None)
        current_amount[key]=current_amount.get(key,Decimal("0"))+amount
        current_tax[key]=current_tax.get(key,Decimal("0"))+tax_amount
        current_qty[key]=current_qty.get(key,Decimal("0"))+qty
        net += amount; tax += tax_amount
    doc.net_amount=net; doc.tax_amount=tax; doc.grand_total=net+tax

def _account_for_party(doc,kind):
    party_type="Customer" if kind=="Sales" else "Supplier"
    party=row(party_type,doc.party,"name","control_account")
    if not party or not party["control_account"]: throw(f"Configure the {party_type} control account.")
    return party["control_account"]

class ReturnPostingAdapter:
    def __init__(self,kind): self.kind=kind
    def build_posting(self,source):
        sales=self.kind=="Sales"; party_type="Customer" if sales else "Supplier"
        control=_account_for_party(source,self.kind)
        lines=[PostingLine(account=control,debit=0 if sales else source.grand_total,credit=source.grand_total if sales else 0,party_type=party_type,party=source.party,line_description=f"{self.kind} Return {source.name}",transaction_date=source.return_date,external_reference=source.source_invoice)]
        for line in source.lines:
            # A returned STOCK item leaves the warehouse, so the supplier credit goes to the item's own inventory (control) account,
            # as an ERPNext debit note with stock update does. The stock ledger then moves only the price difference to variance.
            account=line.account
            if not sales:
                from velora_erp.finance.inventory.ledger import is_stock_item, inventory_settings, _asset_account
                if is_stock_item(getattr(line,"item_code",None)):
                    account=_asset_account(get_doc("Inventory Item",line.item_code,ignore_permissions=True),inventory_settings())
            lines.append(PostingLine(account=account,debit=line.amount if sales else 0,credit=0 if sales else line.amount,line_description=f"Return: {line.description}",cost_centre=line.cost_centre or None,transaction_date=source.return_date))
            if _d(line.tax_amount):
                lines.append(PostingLine(account=line.tax_account,debit=line.tax_amount if sales else 0,credit=0 if sales else line.tax_amount,line_description=f"Tax reversal: {line.description}",transaction_date=source.return_date,tax_code=line.tax_code or None,tax_rate=line.tax_rate or 0,taxable_amount=line.amount,tax_amount=line.tax_amount))
        return PostingInstruction(posting_date=source.posting_date,currency=source.currency,exchange_rate=source.exchange_rate,idempotency_key=f"{self.kind.lower()}-return:{source.name}:original",lines=tuple(lines),remarks=source.narration)

def submit_return(doc,kind):
    ensure_approved(doc,required=True)
    batch=post_source_document(doc,ReturnPostingAdapter(kind))
    persist_posting_batch_link(doc,batch)
    return batch
