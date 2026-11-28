from decimal import Decimal, ROUND_HALF_UP
from velora import Document, throw, get_doc, get_list, new_doc
from velora_erp.finance.source_documents import finance_settings
from velora_erp.finance.validation import row
from velora_erp.finance.doctype._utils import db_update

CENT = Decimal("0.01")
def D(v): return Decimal(str(v if v not in (None, "") else 0))
def M(v): return D(v).quantize(CENT, rounding=ROUND_HALF_UP)
def account(name, root):
    a=row("Account",name,"name","root_type","disabled")
    if not a or a["disabled"] or a["root_type"] != root:
        throw(f"{name!r} must be an active {root} account.")
    return a

def calculate_temporary_difference(financial_carrying_amount, tax_base, tax_rate, recognise_dta=True):
    difference=M(D(financial_carrying_amount)-D(tax_base))
    rate=D(tax_rate)
    if rate < 0 or rate > 100:
        throw("Tax rate must be between 0 and 100%.")
    gross=M(abs(difference)*rate/100)
    kind="Taxable" if difference>0 else "Deductible" if difference<0 else "None"
    recognised=gross if kind=="Taxable" or (kind=="Deductible" and recognise_dta) else Decimal("0.00")
    return {"temporary_difference":difference,"difference_type":kind,"gross_deferred_tax":gross,"recognised_deferred_tax":recognised}

def calculate_deferred_tax_movement(current_dta, current_dtl, previous_dta, previous_dtl):
    delta_dta=M(D(current_dta)-D(previous_dta))
    delta_dtl=M(D(current_dtl)-D(previous_dtl))
    return {"delta_dta":delta_dta,"delta_dtl":delta_dtl,"tax_expense":M(delta_dtl-delta_dta)}

def populate_fixed_asset_book_differences(doc):
    """Build draft temporary-difference rows from financial assets and a selected tax book.

    Tax-book balances are used as tax bases; the routine never posts or changes either book.
    Generated DTA recognition is disabled by default pending recoverability assessment.
    """
    if not getattr(doc, "auto_populate_fixed_asset_books", 0):
        return
    book = getattr(doc, "tax_depreciation_book", None)
    rate = D(getattr(doc, "default_tax_rate", 0))
    basis = (getattr(doc, "default_tax_rate_basis", "") or "").strip()
    if not book or rate < 0 or rate > 100 or not basis:
        throw("Select a Tax Depreciation Book and provide a valid tax rate with its enactment reference.")
    book_doc = get_doc("Fixed Asset Depreciation Book", book, ignore_permissions=True)
    if book_doc.book_type != "Tax" or book_doc.disabled:
        throw("The selected depreciation book must be an active Tax book.")
    assets = [a for a in get_list("Fixed Asset", filters={}, fields=["name", "carrying_amount", "status"], limit=100000, ignore_permissions=True) if a.get("status") in ("Active", "Leased")]
    balances = get_list("Fixed Asset Book Balance", filters={"depreciation_book": book}, fields=["name", "asset", "carrying_amount"], limit=100000, ignore_permissions=True)
    by_asset = {r["asset"]: r for r in balances}
    doc.lines = []
    for asset in assets:
        balance = by_asset.get(asset["name"])
        if not balance:
            continue
        doc.append("lines", {"description": f"Fixed asset tax basis: {asset['name']}", "source_type": "Fixed Asset", "source_reference": asset["name"], "source_asset": asset["name"], "source_depreciation_book": book, "financial_carrying_amount": asset.get("carrying_amount") or 0, "tax_base": balance.get("carrying_amount") or 0, "tax_rate": rate, "tax_rate_basis": basis, "recognise_deferred_tax_asset": 0, "notes": "Generated from the Financial Fixed Asset register and selected Tax Depreciation Book. Review tax basis, temporary difference and recognition criteria before submission."})
    if not doc.lines:
        throw("No matching Fixed Asset Book Balance records were found for the selected Tax Depreciation Book.")
    doc._link_children()


def build_deferred_tax_posting_lines(doc):
    movement_data=calculate_deferred_tax_movement(doc.deferred_tax_asset,doc.deferred_tax_liability,doc.previous_deferred_tax_asset,doc.previous_deferred_tax_liability)
    delta_dta=movement_data["delta_dta"]
    delta_dtl=movement_data["delta_dtl"]
    movement=movement_data["tax_expense"]
    lines=[]
    if delta_dta > 0:
        lines.append({"account":doc.deferred_tax_asset_account,"entry_type":"Deferred Tax Asset","debit":delta_dta,"credit":0,"line_description":"Increase in recognised deferred tax asset"})
    elif delta_dta < 0:
        lines.append({"account":doc.deferred_tax_asset_account,"entry_type":"Deferred Tax Asset","debit":0,"credit":-delta_dta,"line_description":"Reversal of deferred tax asset"})
    if delta_dtl > 0:
        lines.append({"account":doc.deferred_tax_liability_account,"entry_type":"Deferred Tax Liability","debit":0,"credit":delta_dtl,"line_description":"Increase in deferred tax liability"})
    elif delta_dtl < 0:
        lines.append({"account":doc.deferred_tax_liability_account,"entry_type":"Deferred Tax Liability","debit":-delta_dtl,"credit":0,"line_description":"Reversal of deferred tax liability"})
    if movement > 0:
        lines.append({"account":doc.deferred_tax_expense_account,"entry_type":"Deferred Tax Expense","debit":movement,"credit":0,"line_description":"Deferred tax expense"})
    elif movement < 0:
        lines.append({"account":doc.deferred_tax_benefit_account,"entry_type":"Deferred Tax Benefit","debit":0,"credit":-movement,"line_description":"Deferred tax benefit"})
    return lines

def sync_deferred_tax_posting_inbox(doc):
    """Create/update a pending review proposal; this function never posts to GL."""
    if getattr(doc,"posting_inbox",None):
        inbox=get_doc("Deferred Tax Posting Inbox",doc.posting_inbox,ignore_permissions=True)
        if inbox.docstatus==1 or inbox.approval_status!="Pending":
            throw("This assessment already has an approved or posted proposal. Create a new assessment for any further adjustment.")
        if inbox.status=="Superseded":
            db_update(doc,posting_inbox=None,status="Draft")
            doc.posting_inbox=None
            doc.status="Draft"
            inbox=None
    else:
        inbox=None
    lines=build_deferred_tax_posting_lines(doc)
    if not lines:
        if inbox:
            db_update(inbox,status="Superseded")
            db_update(doc,posting_inbox=None,status="Draft")
            doc.posting_inbox=None
            doc.status="Draft"
        return
    settings=finance_settings()
    debit=sum((D(x.get("debit")) for x in lines),Decimal("0"))
    credit=sum((D(x.get("credit")) for x in lines),Decimal("0"))
    if debit!=credit:
        throw("Deferred tax proposal is not balanced. No posting proposal was created.")
    values={"source_assessment":doc.name,"posting_date":doc.assessment_date,"currency":settings["base_currency"],"exchange_rate":1,"remarks":doc.remarks or f"Deferred tax assessment {doc.name}","total_debit":M(debit),"total_credit":M(credit),"status":"Pending Review","approval_status":"Pending","lines":lines}
    if inbox:
        inbox.lines=[]
        for line in lines: inbox.append("lines",line)
        for key,value in values.items():
            if key!="lines": setattr(inbox,key,value)
        inbox.save(ignore_permissions=True)
        db_update(doc,status="Pending Review")
        doc.status="Pending Review"
    else:
        inbox=new_doc("Deferred Tax Posting Inbox",**{k:v for k,v in values.items() if k!="lines"})
        for line in lines: inbox.append("lines",line)
        inbox.insert(ignore_permissions=True)
        db_update(doc,posting_inbox=inbox.name,status="Pending Review")
        doc.posting_inbox=inbox.name
        doc.status="Pending Review"


class DeferredTaxAssessment(Document):
    def validate(self):
        populate_fixed_asset_book_differences(self)
        if not self.assessment_date or not self.lines:
            throw("Assessment Date and at least one temporary-difference line are required.")
        account(self.deferred_tax_asset_account,"Asset")
        account(self.deferred_tax_liability_account,"Liability")
        account(self.deferred_tax_expense_account,"Expense")
        account(self.deferred_tax_benefit_account,"Income")
        taxable=deductible=dta=dtl=Decimal("0")
        for i,line in enumerate(self.lines,1):
            carrying=D(line.financial_carrying_amount); tax_base=D(line.tax_base); rate=D(line.tax_rate)
            if rate < 0 or rate > 100: throw(f"Line {i}: tax rate must be between 0 and 100%.")
            result=calculate_temporary_difference(carrying,tax_base,rate,bool(line.recognise_deferred_tax_asset))
            line.temporary_difference=result["temporary_difference"]
            line.difference_type=result["difference_type"]
            line.gross_deferred_tax=result["gross_deferred_tax"]
            line.recognised_deferred_tax=result["recognised_deferred_tax"]
            if line.difference_type=="Taxable": taxable += line.temporary_difference; dtl += line.recognised_deferred_tax
            elif line.difference_type=="Deductible":
                deductible += -line.temporary_difference
                if line.recognise_deferred_tax_asset and not (line.recoverability_basis or "").strip():
                    throw(f"Line {i}: document probable future taxable profits supporting recognition of the deferred tax asset.")
                dta += line.recognised_deferred_tax
        self.taxable_temporary_differences=M(taxable)
        self.deductible_temporary_differences=M(deductible)
        self.deferred_tax_liability=M(dtl); self.deferred_tax_asset=M(dta)
        self.net_deferred_tax_liability=M(dtl-dta)
        prior=get_list("Deferred Tax Assessment",filters={},fields=["name","assessment_date","status"],limit=10000,ignore_permissions=True)
        same_date=[r for r in prior if r["name"] != self.name and r.get("status") in ("Pending Review","Approved","Posted") and str(r.get("assessment_date") or "") == str(self.assessment_date)]
        if same_date:
            throw("A pending or posted Deferred Tax Assessment already exists for this assessment date. Complete or resolve that assessment before creating another.")
        prior=[r for r in prior if r["name"] != self.name and r.get("status")=="Posted" and str(r.get("assessment_date") or "") < str(self.assessment_date)]
        if prior:
            prior.sort(key=lambda r:(str(r.get("assessment_date") or ""),r["name"]))
            latest=get_doc("Deferred Tax Assessment",prior[-1]["name"],ignore_permissions=True)
            self.previous_net_liability=M(latest.net_deferred_tax_liability)
            self.previous_deferred_tax_asset=M(latest.deferred_tax_asset)
            self.previous_deferred_tax_liability=M(latest.deferred_tax_liability)
        else:
            self.previous_net_liability=Decimal("0.00")
            self.previous_deferred_tax_asset=Decimal("0.00")
            self.previous_deferred_tax_liability=Decimal("0.00")
        self.movement=M((D(self.deferred_tax_liability)-D(self.previous_deferred_tax_liability))-(D(self.deferred_tax_asset)-D(self.previous_deferred_tax_asset)))
    def after_insert(self):
        if self.docstatus==0:
            sync_deferred_tax_posting_inbox(self)
    def on_update(self):
        if self.docstatus==0:
            sync_deferred_tax_posting_inbox(self)
    def before_submit(self):
        throw("Deferred Tax Assessment is a calculation document only. Review and approve its automatically generated Deferred Tax Posting Inbox proposal to post the journal.")
def before_delete(self):
        if self.docstatus==1 or getattr(self,"posting_inbox",None):
            throw("A deferred tax assessment linked to a posting proposal is retained for audit. Resolve it through the inbox workflow rather than deleting it.")
