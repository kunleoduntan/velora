from __future__ import annotations
import hashlib, json, re
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from velora import Document, db, get_doc, get_list, new_doc, throw
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, approval_required
from velora_erp.finance.validation import row
from velora_erp.finance.doctype._utils import db_update, db_update_child
from .payroll_engine import calculate_payroll, payroll_posting_lines, money, PayrollCalculationError, allocate_loan_recoveries

CENT=Decimal("0.01")
ZERO=Decimal("0")
def D(v): return Decimal(str(v if v not in (None, "") else 0))
def _account(name, roots=None, party=False):
    a=row("Account",name,"name","root_type","disabled","requires_party","account_currency") if name else None
    if not a or a["disabled"]: throw(f"Account {name!r} does not exist or is disabled.")
    if roots and a["root_type"] not in roots: throw(f"Account {name} must be a {' or '.join(roots)} account.")
    if party and not a["requires_party"]: throw(f"Account {name} must be configured for party tracking.")
    return a

def _json_safe(value):
    if isinstance(value,Decimal): return str(value)
    if isinstance(value,dict): return {str(k):_json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [_json_safe(v) for v in value]
    return value

def _fingerprint(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def _tax_credit_fingerprint(payroll_run, employee, tax_row):
    calculation={k:v for k,v in tax_row.items() if k not in {"credit_review_reference","approved_credit_amount"}}
    payload={"payroll_run":payroll_run,"employee":employee,"component_code":tax_row.get("component_code"),
        "tax_rule":tax_row.get("tax_rule"),"tax_year_start":tax_row.get("tax_year_start"),
        "credit_amount":str(tax_row.get("refund_credit_amount") or "0"),
        "tax_liability_account":tax_row.get("tax_liability_account"),"calculation":calculation}
    return _fingerprint(payload)

def _as_rows(value):
    if isinstance(value,str):
        try: value=json.loads(value or "[]")
        except Exception: return []
    return value if isinstance(value,list) else []

def _tax_year_start(jurisdiction, period_end):
    end=date.fromisoformat(str(period_end)[:10])
    month=int(jurisdiction.tax_year_start_month or 1); day=int(jurisdiction.tax_year_start_day or 1)
    year=end.year
    try: start=date(year,month,day)
    except ValueError:
        # A configured 29 February start is valid; in non-leap years it begins on 28 February.
        start=date(year,month,28)
    if end<start:
        year-=1
        try: start=date(year,month,day)
        except ValueError: start=date(year,month,28)
    return start

def _prior_payroll_tax_context(employee, component_code, tax_rule, jurisdiction_name, period_start, period_end, periods_per_year, pay_frequency):
    jurisdiction=get_doc("Payroll Tax Jurisdiction",jurisdiction_name,ignore_permissions=True)
    year_start=_tax_year_start(jurisdiction,period_end)
    overlapping=get_list("Salary Slip",filters=[["employee","=",employee],["docstatus","=",1],
        ["period_start","<=",period_end],["period_end",">=",period_start]],
        fields=["name"],limit=100,ignore_permissions=True)
    if overlapping:
        throw(f"Employee {employee}: the current payroll period overlaps an already posted Salary Slip; duplicate cumulative PAYE periods are blocked.")
    slips=get_list("Salary Slip",filters=[["employee","=",employee],["docstatus","=",1],
        ["period_end",">=",year_start],["period_end","<",period_start]],
        fields=["name","period_start","period_end"],limit=10000,ignore_permissions=True)
    slips=sorted(slips,key=lambda x:(str(x.get("period_start")),str(x.get("period_end")),str(x.get("name"))))
    previous_end=None; seen_periods=set(); taxable=ZERO; withheld=ZERO
    for summary in slips:
        start=str(summary.get("period_start")); end=str(summary.get("period_end"))
        if start<str(year_start):
            throw(f"Employee {employee}: a posted Salary Slip crosses the configured tax-year boundary; cumulative PAYE requires period-aligned tax-year dates.")
        if start>end or (previous_end and start<=previous_end):
            throw(f"Employee {employee}: overlapping or invalid posted Salary Slip periods prevent cumulative PAYE calculation.")
        key=(start,end)
        if key in seen_periods: throw(f"Employee {employee}: duplicate posted Salary Slip period prevents cumulative PAYE calculation.")
        seen_periods.add(key); previous_end=end
        slip=get_doc("Salary Slip",summary["name"],ignore_permissions=True)
        prior_run=get_doc("Payroll Run",slip.payroll_run,ignore_permissions=True) if getattr(slip,"payroll_run",None) else None
        if prior_run and prior_run.pay_frequency!=pay_frequency:
            throw(f"Employee {employee}: pay frequency changed within the tax year; cumulative PAYE requires a consistent payroll frequency or a reviewed transition calculation.")
        for item in slip.lines or []:
            if item.component_type=="Earning" and bool(getattr(item,"taxable",False)):
                taxable+=D(item.amount or 0)
            if item.component_type=="Deduction" and item.component_code==component_code:
                withheld+=D(item.amount or 0)
        # Preserve withholding when a payroll structure changes the PAYE component code but keeps the same approved rule.
        if not any(item.component_type=="Deduction" and item.component_code==component_code for item in (slip.lines or [])):
            for detail in _as_rows(getattr(slip,"tax_computation",None)):
                if detail.get("tax_rule")==tax_rule:
                    withheld+=D(detail.get("actual_withheld",detail.get("period_tax",0)) or 0)
    elapsed=len(slips)
    if elapsed>=int(periods_per_year):
        throw(f"Employee {employee}: cumulative PAYE has exhausted the configured annual payroll periods before this run.")
    return {"tax_year_start":year_start.isoformat(),"prior_ytd_taxable_income":taxable,
        "prior_tax_withheld":withheld,"prior_periods_elapsed":elapsed}

def _approved_tax_credit_review(payroll_run, employee, tax_row):
    fingerprint=_tax_credit_fingerprint(payroll_run,employee,tax_row)
    rows=get_list("Tax Refund Credit Review",filters=[["payroll_run","=",payroll_run],
        ["employee","=",employee],["tax_component_code","=",tax_row.get("component_code")]],
        fields=["name","approval_status","status","source_calculation_fingerprint","approved_credit_amount"],
        limit=20,ignore_permissions=True)
    matches=[x for x in rows if x.get("source_calculation_fingerprint")==fingerprint and
        x.get("approval_status")=="Approved" and x.get("status")=="Approved" and
        money(x.get("approved_credit_amount") or 0)==money(tax_row.get("refund_credit_amount") or 0)]
    return matches[0] if len(matches)==1 else None
def _approval(doc): validate_approval_transition(doc)
def _approved(doc): ensure_approved(doc,required=True)
def _persist(doc,batch): db_update(doc,posting_batch=batch.name); return batch

def loan_schedule(*, principal, annual_rate, months, first_date, method="Equal Instalment"):
    principal=money(principal); rate=D(annual_rate)/Decimal("1200"); months=int(months)
    if principal<=0 or months<=0 or rate<0 or rate>Decimal("1"): raise ValueError("Loan principal, term or interest rate is invalid")
    due=date.fromisoformat(str(first_date)[:10]); balance=principal; rows=[]
    if method not in ("Equal Instalment","Equal Principal"): raise ValueError("Unsupported loan repayment method")
    if method=="Equal Instalment" and rate:
        factor=(Decimal("1")+rate)**months
        instalment=money(principal*rate*factor/(factor-1))
    else: instalment=money(principal/Decimal(months))
    for i in range(1,months+1):
        interest=money(balance*rate)
        principal_due=money(min(balance,instalment-interest if method=="Equal Instalment" else principal/Decimal(months)))
        if i==months: principal_due=balance
        total=money(principal_due+interest); closing=money(balance-principal_due)
        rows.append({"installment_no":i,"due_date":due.isoformat(),"opening_balance":balance,"principal_amount":principal_due,"interest_amount":interest,"total_due":total,"closing_balance":closing,"paid_amount":0})
        balance=closing
        import calendar
        was_month_end=due.day==calendar.monthrange(due.year,due.month)[1]
        y,m=due.year+(due.month)//12,(due.month)%12+1
        next_last=calendar.monthrange(y,m)[1]
        due=due.replace(year=y,month=m,day=next_last if was_month_end else min(due.day,next_last))
    return rows

def apply_loan_schedule_recovery(loan, *, principal_amount, interest_amount=0, paid_on=None):
    """Allocate an approved principal/interest recovery to oldest due instalments."""
    principal_left=money(principal_amount); interest_left=money(interest_amount)
    if principal_left<0 or interest_left<0: throw("Loan recovery amounts cannot be negative.")
    rows=sorted(list(loan.schedule or []),key=lambda x:(str(x.due_date),int(x.installment_no or 0)))
    for item in rows:
        if paid_on and str(item.due_date)>str(paid_on): continue
        principal_due=money(D(item.principal_amount)-D(getattr(item,"paid_principal",0) or 0))
        interest_due=money(D(item.interest_amount)-D(getattr(item,"paid_interest",0) or 0))
        p=min(principal_left,principal_due); i=min(interest_left,interest_due)
        if not p and not i: continue
        new_p=money(D(getattr(item,"paid_principal",0) or 0)+p)
        new_i=money(D(getattr(item,"paid_interest",0) or 0)+i)
        new_total=money(new_p+new_i)
        status="Paid" if new_p>=D(item.principal_amount) and new_i>=D(item.interest_amount) else "Partially Paid" if new_total else "Pending"
        if item.name:
            db_update_child("Employee Loan Schedule Line",item.name,paid_principal=new_p,paid_interest=new_i,paid_amount=new_total,status=status)
        item.paid_principal=new_p; item.paid_interest=new_i; item.paid_amount=new_total; item.status=status
        principal_left=money(principal_left-p); interest_left=money(interest_left-i)
        if principal_left==0 and interest_left==0: break
    if principal_left>0 and interest_left==0 and paid_on:
        # Early repayment: principal beyond what has fallen due reduces the later instalments, oldest first.
        for item in rows:
            if str(item.due_date)<=str(paid_on): continue
            principal_due=money(D(item.principal_amount)-D(getattr(item,"paid_principal",0) or 0))
            p=min(principal_left,principal_due)
            if not p: continue
            new_p=money(D(getattr(item,"paid_principal",0) or 0)+p)
            new_total=money(new_p+D(getattr(item,"paid_interest",0) or 0))
            if item.name: db_update_child("Employee Loan Schedule Line",item.name,paid_principal=new_p,paid_amount=new_total,status="Partially Paid")
            item.paid_principal=new_p; item.paid_amount=new_total; item.status="Partially Paid"
            principal_left=money(principal_left-p)
            if principal_left==0: break
        # Interest follows the reduced balance: each unpaid later instalment is charged on the principal still outstanding from it onward;
        # instalments whose principal was prepaid carry no further interest. Interest already recovered is never reduced.
        monthly=D(getattr(loan,"annual_interest_rate",0) or 0)/Decimal("1200")
        future=[x for x in rows if str(x.due_date)>str(paid_on)]
        unpaid=[money(D(x.principal_amount)-D(getattr(x,"paid_principal",0) or 0)) for x in future]
        for n,item in enumerate(future):
            paid_i=D(getattr(item,"paid_interest",0) or 0)
            new_i=ZERO if unpaid[n]==0 else money(sum(unpaid[n:],ZERO)*monthly)
            new_i=max(new_i,paid_i)
            total=money(D(item.principal_amount)+new_i)
            status="Paid" if unpaid[n]==0 and new_i<=paid_i else ("Partially Paid" if D(getattr(item,"paid_principal",0) or 0)+paid_i>0 else "Pending")
            paid_total=money(D(getattr(item,"paid_principal",0) or 0)+paid_i)
            if item.name: db_update_child("Employee Loan Schedule Line",item.name,interest_amount=new_i,total_due=total,paid_amount=paid_total,status=status)
            item.interest_amount=new_i; item.total_due=total; item.paid_amount=paid_total; item.status=status
        loan_interest=money(sum((D(x.interest_amount) for x in rows),ZERO))
        db_update(loan,total_interest=loan_interest,total_repayment=money(D(loan.principal_amount)+loan_interest))
    if principal_left>0 or interest_left>0:
        throw("Loan recovery exceeds the unpaid scheduled principal or interest due by the recovery date.")
    return True

def _check_rules(code, calculation_type, formula, condition, known=None):
    """Reject an unusable formula/condition when it is SAVED, not when payroll is run. With `known` (a structure's variables) unknown names are rejected too."""
    from .payroll_engine import PayrollCalculationError, check_expression, check_expression_names
    try:
        if calculation_type=="Formula": names=check_expression(formula,"formula")
        else: names=set()
        cond_names=check_expression(condition,"condition") if condition else set()
        if known is not None: check_expression_names(names|cond_names,known,f"Component {code}")
    except PayrollCalculationError as exc:
        throw(f"Component {code}: {exc}")

class SalaryComponent(Document):
    def validate(self):
        self.component_code=(self.component_code or "").strip().upper()
        self.component_name=(self.component_name or "").strip()
        if not self.component_code or not self.component_name: throw("Component Code and Component Name are required.")
        if self.component_type not in ("Earning","Deduction","Employer Contribution","Loan Repayment","Loan Interest Recovery","Advance Recovery"): throw("Select a valid salary component type.")
        if self.calculation_type not in ("Fixed","Percentage of Base","Percentage of Gross","Percentage of Pensionable Gross","Formula","Input","Progressive Tax","Scheduled Loan Deduction","Scheduled Loan Interest"): throw("Select a valid calculation type.")
        if self.calculation_type=="Scheduled Loan Deduction" and self.component_type!="Loan Repayment": throw("Scheduled Loan Deduction must be a Loan Repayment component.")
        if self.calculation_type=="Scheduled Loan Interest" and self.component_type!="Loan Interest Recovery": throw("Scheduled Loan Interest must be a Loan Interest Recovery component.")
        if self.calculation_type in ("Scheduled Loan Deduction","Scheduled Loan Interest") and not self.loan_type: throw("Scheduled loan components must be mapped to an Employee Loan Type.")
        if self.calculation_type=="Progressive Tax" and self.component_type!="Deduction": throw("Progressive Tax must be configured as a Deduction component.")
        if self.calculation_type=="Fixed" and D(self.amount)<0: throw("Fixed salary component amount cannot be negative.")
        if self.calculation_type in ("Percentage of Base","Percentage of Gross","Percentage of Pensionable Gross") and not (0<=D(self.rate)<=1000): throw("Salary component rate must be between 0 and 1000 percent.")
        _check_rules(self.component_code, self.calculation_type, getattr(self,"formula",None), getattr(self,"condition",None))
        mapped_account=getattr(self,"account",None)
        if self.component_type=="Employer Contribution":
            self.employer_expense_account=getattr(self,"employer_expense_account",None) or self.debit_account
            self.employer_payable_account=getattr(self,"employer_payable_account",None) or self.credit_account
            if not self.employer_expense_account or not self.employer_payable_account:
                throw("Employer Contribution requires both Employer Contribution Expense Account and Employer Contribution Payable Account.")
            _account(self.employer_expense_account,["Expense"]); _account(self.employer_payable_account,["Liability"])
            self.debit_account=self.employer_expense_account; self.credit_account=self.employer_payable_account
        elif mapped_account:
            if self.component_type=="Earning":
                _account(mapped_account,["Expense"]); self.debit_account=mapped_account; self.credit_account=None
            elif self.component_type=="Deduction":
                _account(mapped_account,["Asset","Liability","Income"]); self.credit_account=mapped_account; self.debit_account=None
            elif self.component_type=="Loan Repayment":
                _account(mapped_account,["Asset"],party=True); self.credit_account=mapped_account; self.debit_account=None
            elif self.component_type=="Loan Interest Recovery":
                _account(mapped_account,["Income"]); self.credit_account=mapped_account; self.debit_account=None
            elif self.component_type=="Advance Recovery":
                _account(mapped_account,["Asset"],party=True); self.credit_account=mapped_account; self.debit_account=None
        else:
            if self.component_type in ("Earning","Employer Contribution"):
                _account(self.debit_account,["Expense"])
            if self.component_type in ("Deduction","Employer Contribution","Loan Repayment","Loan Interest Recovery","Advance Recovery"):
                _account(self.credit_account,["Asset","Liability","Income"])

class PayrollInput(Document):
    def validate(self):
        _approval(self)
        if not all((self.employee,self.salary_component,self.effective_from,self.input_frequency,self.input_mode)): throw("Employee, Salary Component, Effective From, Frequency and Input Mode are required.")
        if not D(self.input_value).is_finite(): throw("Payroll Input must be a finite numeric value.")
        if self.effective_to and str(self.effective_to)<str(self.effective_from): throw("Payroll Input effective dates are invalid.")
        component=get_doc("Salary Component",self.salary_component,ignore_permissions=True)
        if component.disabled: throw("A disabled Salary Component cannot receive Payroll Inputs.")
        expected=getattr(component,"input_fieldname",None)
        if not self.input_fieldname: self.input_fieldname=expected or component.component_code.lower()
        if expected and self.input_fieldname!=expected: throw(f"Payroll Input fieldname must match the Salary Component mapping {expected}.")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}",str(self.input_fieldname)): throw("Payroll Input Fieldname must be a valid lowercase fieldname.")
        fingerprint=_fingerprint({"employee":self.employee,"component":self.salary_component,"field":self.input_fieldname,"value":str(self.input_value),"from":str(self.effective_from),"to":str(self.effective_to or ""),"frequency":self.input_frequency,"mode":self.input_mode})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved Payroll Inputs are immutable; reset approval before changing them.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self):
        _approved(self)
        if not self.approval_hash: throw("Independent approval is required before activating a Payroll Input.")
    def on_submit(self): db_update(self,status="Active")
    def before_cancel(self):
        if self.status=="Processed" or getattr(self,"processed_payroll_run",None): throw(f"This input was used by Payroll Run {self.processed_payroll_run}. Cancel that payroll run first.")

class SalaryStructure(Document):
    """Two tables, one engine: Earnings and Deductions & Contributions. `components` is the combined, read-only view the payroll engine uses;
    writing `components` (API clients, imports, older scripts) routes each row to the right table by its component type."""

    @property
    def components(self):
        return list(self.earnings or [])+list(self.deductions or [])

    def update(self, values):
        values=dict(values); legacy=values.pop("components",None)
        super().update(values)
        if legacy is not None:
            self.earnings=[]; self.deductions=[]
            for row in legacy: self._route(row)
        return self

    def _route(self, row):
        data=row if isinstance(row,dict) else row.as_dict()
        kind=data.get("component_type")
        if not kind and data.get("salary_component"):
            try: kind=get_doc("Salary Component",data["salary_component"],ignore_permissions=True).component_type
            except Exception: kind="Earning"      # unknown component: validation reports it
        self.append("earnings" if (kind or "Earning")=="Earning" else "deductions",row)

    def validate(self):
        _approval(self)
        if not self.structure_name or not self.currency or not self.components: throw("Structure Name, Currency and at least one component are required.")
        codes=set(); input_fields=set(); rows=[]
        for index,line in enumerate(self.components,1):
            comp=get_doc("Salary Component",line.salary_component,ignore_permissions=True)
            if comp.disabled: throw(f"Salary component {comp.name} is disabled.")
            if comp.component_code in codes: throw(f"Duplicate salary component {comp.component_code}.")
            codes.add(comp.component_code)
            line.component_code=comp.component_code; line.component_name=comp.component_name; line.component_type=comp.component_type; line.calculation_type=comp.calculation_type
            line.amount=comp.amount if line.amount in (None,"") else line.amount
            line.rate=comp.rate if line.rate in (None,"") else line.rate
            line.formula=line.formula or comp.formula
            line.condition=getattr(line,"condition",None) or getattr(comp,"condition",None)
            line.input_fieldname=getattr(line,"input_fieldname",None) or getattr(comp,"input_fieldname",None)
            line.input_label=getattr(line,"input_label",None) or getattr(comp,"input_label",None)
            line.input_location=getattr(line,"input_location",None) or getattr(comp,"input_location",None)
            line.input_required=int(bool(getattr(line,"input_required",False) or getattr(comp,"input_required",False)))
            line.input_default=getattr(line,"input_default",None) if getattr(line,"input_default",None) not in (None,"") else getattr(comp,"input_default",None)
            line.loan_type=getattr(line,"loan_type",None) or getattr(comp,"loan_type",None)
            line.tax_rule=getattr(line,"tax_rule",None) or getattr(comp,"tax_rule",None)
            line.periods_per_year=getattr(line,"periods_per_year",None) or getattr(comp,"periods_per_year",12)
            line.annual_relief=getattr(line,"annual_relief",None) if getattr(line,"annual_relief",None) not in (None,"") else getattr(comp,"annual_relief",0)
            line.cost_centre=getattr(line,"cost_centre",None) or getattr(comp,"cost_centre",None)
            line.business_unit=getattr(line,"business_unit",None) or getattr(comp,"business_unit",None)
            if line.input_fieldname:
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}",str(line.input_fieldname)):
                    throw(f"Component {comp.component_code}: input fieldname must be a valid lowercase fieldname.")
                if line.input_fieldname in input_fields: throw(f"Salary Slip input field {line.input_fieldname} is mapped more than once in this structure.")
                input_fields.add(line.input_fieldname)
            line.sequence=line.sequence if line.sequence not in (None,"") else comp.sequence
            line.prorate_by_attendance=int(bool(line.prorate_by_attendance or comp.prorate_by_attendance))
            line.taxable=int(bool(line.taxable or comp.taxable)); line.pensionable=int(bool(line.pensionable or comp.pensionable))
            line.hide_on_payslip=int(bool(getattr(line,"hide_on_payslip",0) or getattr(comp,"hide_on_payslip",0)))
            line.reduces_taxable_income=int(bool(getattr(line,"reduces_taxable_income",0) or getattr(comp,"reduces_taxable_income",0)))
            line.account=getattr(line,"account",None) or getattr(comp,"account",None)
            line.statutory_scheme=getattr(line,"statutory_scheme",None) or getattr(comp,"statutory_scheme",None)
            if line.component_type=="Employer Contribution":
                line.employer_expense_account=getattr(line,"employer_expense_account",None) or getattr(comp,"employer_expense_account",None) or comp.debit_account
                line.employer_payable_account=getattr(line,"employer_payable_account",None) or getattr(comp,"employer_payable_account",None) or comp.credit_account
                if not line.employer_expense_account or not line.employer_payable_account:
                    throw(f"Component {comp.component_code}: both employer contribution expense and payable accounts are required.")
                _account(line.employer_expense_account,["Expense"]); _account(line.employer_payable_account,["Liability"])
                line.debit_account=line.employer_expense_account; line.credit_account=line.employer_payable_account
            elif line.account and line.component_type=="Earning":
                line.debit_account=line.account; line.credit_account=None
            elif line.account and line.component_type in ("Deduction","Loan Repayment","Loan Interest Recovery","Advance Recovery"):
                line.credit_account=line.account; line.debit_account=None
            else:
                line.debit_account=line.debit_account or comp.debit_account; line.credit_account=line.credit_account or comp.credit_account
            if line.calculation_type=="Fixed" and D(line.amount)<0: throw(f"Component {comp.component_code}: amount cannot be negative.")
            if line.calculation_type in ("Percentage of Base","Percentage of Gross","Percentage of Pensionable Gross") and D(line.rate)<0: throw(f"Component {comp.component_code}: rate cannot be negative.")
            if line.component_type in ("Earning","Employer Contribution"):
                _account(line.debit_account,["Expense"])
            if line.component_type=="Employer Contribution":
                _account(line.credit_account,["Liability"])
            elif line.component_type in ("Deduction","Loan Repayment","Advance Recovery"):
                _account(line.credit_account,["Asset","Liability","Income"])
            rows.append({"code":line.component_code,"type":line.component_type,"calc":line.calculation_type,"amount":str(line.amount or 0),"rate":str(line.rate or 0),"formula":line.formula or "","condition":line.condition or "","input_fieldname":line.input_fieldname or "","loan_type":line.loan_type or "","tax_rule":line.tax_rule or "","periods_per_year":line.periods_per_year or 12,"annual_relief":str(line.annual_relief or 0),"sequence":line.sequence or 100,"account":getattr(line,"account",None) or "","debit":line.debit_account,"credit":line.credit_account,"employer_expense_account":getattr(line,"employer_expense_account",None),"employer_payable_account":getattr(line,"employer_payable_account",None),"statutory_scheme":getattr(line,"statutory_scheme",None),"cost_centre":line.cost_centre or "","business_unit":line.business_unit or "","prorate":bool(line.prorate_by_attendance),"taxable":bool(line.taxable),"pensionable":bool(line.pensionable)})
        wrong=[r for r in self.earnings if r.component_type!="Earning"]+[r for r in self.deductions if r.component_type=="Earning"]
        if wrong:                          # a row typed into the wrong table is moved, never rejected
            rows=self.components; self.earnings=[r for r in rows if r.component_type=="Earning"]; self.deductions=[r for r in rows if r.component_type!="Earning"]
        from .payroll_engine import STANDARD_NAMES
        ordered=sorted(self.components,key=lambda x:(int(x.sequence or 100),str(x.component_code or "")))
        input_names={x.input_fieldname for x in ordered if x.input_fieldname}
        defined=set(STANDARD_NAMES)|input_names
        for line in ordered:
            _check_rules(line.component_code,line.calculation_type,line.formula,getattr(line,"condition",None),known=defined)
            defined.add(line.component_code)
        progressive=[x for x in self.components if x.calculation_type=="Progressive Tax"]
        for tax_component in progressive:
            if any(x.component_type=="Earning" and x.taxable and int(x.sequence or 0)>=int(tax_component.sequence or 0) for x in self.components):
                throw(f"Progressive Tax component {tax_component.component_code} must be sequenced after all taxable earning components.")
        fingerprint=_fingerprint({"name":self.structure_name,"frequency":self.pay_frequency,"currency":self.currency,"rows":rows})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("An approved Salary Structure is immutable. Reset approval before changing its rules.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self):
        _approved(self)
        if not self.approval_hash: throw("Approve the Salary Structure before submitting it.")

class SalaryStructureAssignment(Document):
    def validate(self):
        _approval(self)
        if not self.employee or not self.salary_structure or not self.effective_from or D(self.base_salary)<=0: throw("Employee, Salary Structure, Effective From and positive Base Salary are required.")
        employee=get_doc("Employee",self.employee,ignore_permissions=True)
        if employee.disabled: throw("A disabled employee cannot receive a salary assignment.")
        structure=get_doc("Salary Structure",self.salary_structure,ignore_permissions=True)
        if structure.docstatus!=1 or structure.disabled: throw("Select an active submitted Salary Structure.")
        if self.currency!=structure.currency: throw("Salary Assignment currency must match the Salary Structure currency.")
        if self.effective_to and str(self.effective_to)<str(self.effective_from): throw("Effective To cannot precede Effective From.")
        fingerprint=_fingerprint({"employee":self.employee,"structure":self.salary_structure,"from":str(self.effective_from),"to":str(self.effective_to or ""),"base_salary":str(self.base_salary),"currency":self.currency,"cost_centre":self.cost_centre or ""})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved Salary Structure Assignments are immutable; reset approval before changing compensation.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self):
        _approved(self)
        if not self.approval_hash: throw("Independent approval is required before activating a Salary Structure Assignment.")
        from velora import get_list
        matches=get_list("Salary Structure Assignment",filters=[["employee","=",self.employee],["docstatus","=",1]],fields=["name","effective_from","effective_to"],limit=100,ignore_permissions=True)
        start=str(self.effective_from)[:10]; end=str(self.effective_to or "9999-12-31")[:10]
        for item in matches:
            if item["name"]==self.name: continue
            other_start=str(item["effective_from"])[:10]; other_end=str(item.get("effective_to") or "9999-12-31")[:10]
            if start<=other_end and other_start<=end: throw(f"Salary Assignment overlaps existing assignment {item['name']} for this employee.")
    def on_submit(self): db_update(self,status="Active")

class PayrollRun(Document):
    ignore_linked_doctypes = ("Salary Slip", "Payroll Input")      # cancelled / put back by the run itself (finance.cancellation)
    def validate(self):
        _approval(self)
        if not all((self.run_title,self.pay_frequency,self.period_start,self.period_end,self.posting_date,self.currency,self.payroll_payable_account)): throw("Payroll Run title, frequency, period, posting date, currency and payroll payable account are required.")
        if str(self.period_start)>str(self.period_end): throw("Payroll period start must not be after period end.")
        _account(self.payroll_payable_account,["Liability"],party=True)
        if not self.employees: throw("Add at least one employee to the Payroll Run.")
        seen=set(); totals={"gross":ZERO,"deductions":ZERO,"employer":ZERO,"net":ZERO,"cost":ZERO}; fingerprint_rows=[]
        for index,line in enumerate(self.employees,1):
            if line.employee in seen: throw(f"Employee {line.employee} appears more than once in this Payroll Run.")
            seen.add(line.employee)
            employee=get_doc("Employee",line.employee,ignore_permissions=True)
            if employee.disabled: throw(f"Employee {line.employee} is disabled.")
            assignment=get_doc("Salary Structure Assignment",line.salary_assignment,ignore_permissions=True)
            if assignment.docstatus!=1 or assignment.employee!=line.employee: throw(f"Payroll line {index}: select a submitted assignment for the same employee.")
            if str(assignment.effective_from)>str(self.period_end) or (assignment.effective_to and str(assignment.effective_to)<str(self.period_start)): throw(f"Payroll line {index}: salary assignment is not effective during this payroll period.")
            if assignment.currency!=self.currency: throw(f"Payroll line {index}: assignment currency differs from the Payroll Run currency.")
            structure=get_doc("Salary Structure",assignment.salary_structure,ignore_permissions=True)
            if structure.docstatus!=1 or structure.disabled or structure.pay_frequency!=self.pay_frequency: throw(f"Payroll line {index}: salary structure is not active or has a different pay frequency.")
            tax_profile=None
            tax_profiles=get_list("Employee Tax Profile",filters=[["employee","=",line.employee],["docstatus","=",1]],fields=["name","jurisdiction","tax_rule","effective_from","effective_to","annual_relief","tax_exempt"],limit=100,ignore_permissions=True)
            overlapping_profiles=[x for x in tax_profiles if str(x.get("effective_from"))<=str(self.period_end) and (not x.get("effective_to") or str(x.get("effective_to"))>=str(self.period_start))]
            if len(overlapping_profiles)>1: throw(f"Payroll line {index}: multiple Employee Tax Profiles overlap the payroll period.")
            if overlapping_profiles:
                candidate=overlapping_profiles[0]
                if str(candidate.get("effective_from"))>str(self.period_start) or (candidate.get("effective_to") and str(candidate.get("effective_to"))<str(self.period_end)):
                    throw(f"Payroll line {index}: Employee Tax Profile must cover the entire payroll period.")
                tax_profile=candidate
            components=[]; seen_tax_rules=set()
            for item in structure.components:
                employee_cost=getattr(employee,"default_cost_centre",None)
                employee_unit=getattr(employee,"default_business_unit",None)
                component_data={"hide_on_payslip":bool(getattr(item,"hide_on_payslip",0)),"reduces_taxable_income":bool(getattr(item,"reduces_taxable_income",0)),"pensionable":bool(getattr(item,"pensionable",0)),"taxable":bool(getattr(item,"taxable",0)),"component_code":item.component_code,"component_name":item.component_name,"component_type":item.component_type,"calculation_type":item.calculation_type,"amount":item.amount,"rate":item.rate,"formula":item.formula,"condition":getattr(item,"condition",None),"input_fieldname":getattr(item,"input_fieldname",None),"input_default":getattr(item,"input_default",0),"loan_type":getattr(item,"loan_type",None),"scheduled_amount":ZERO,"tax_rule":getattr(item,"tax_rule",None),"periods_per_year":getattr(item,"periods_per_year",None) or {"Weekly":52,"Biweekly":26,"Fortnightly":26,"Semi-monthly":24,"Twice Monthly":24,"Monthly":12,"Quarterly":4,"Annual":1,"Annually":1}.get(self.pay_frequency,12),"annual_relief":getattr(item,"annual_relief",0),"sequence":item.sequence,"prorate_by_attendance":bool(item.prorate_by_attendance),"taxable":bool(item.taxable),"pensionable":bool(item.pensionable),"account":getattr(item,"account",None),"employer_expense_account":getattr(item,"employer_expense_account",None) or (item.debit_account if item.component_type=="Employer Contribution" else None),"employer_payable_account":getattr(item,"employer_payable_account",None) or (item.credit_account if item.component_type=="Employer Contribution" else None),"statutory_scheme":getattr(item,"statutory_scheme",None),"debit_account":(getattr(item,"account",None) if item.component_type=="Earning" else (getattr(item,"employer_expense_account",None) or item.debit_account if item.component_type=="Employer Contribution" else item.debit_account)),"credit_account":(getattr(item,"account",None) if item.component_type in ("Deduction","Loan Repayment","Loan Interest Recovery","Advance Recovery") else (getattr(item,"employer_payable_account",None) or item.credit_account if item.component_type=="Employer Contribution" else item.credit_account)),"cost_centre":getattr(line,"cost_centre",None) or assignment.cost_centre or employee_cost or getattr(item,"cost_centre",None) or getattr(structure,"default_cost_centre",None) or self.cost_centre,"business_unit":getattr(line,"business_unit",None) or getattr(assignment,"business_unit",None) or employee_unit or getattr(item,"business_unit",None) or getattr(structure,"default_business_unit",None)}
                if item.calculation_type=="Progressive Tax":
                    if not tax_profile: throw(f"Payroll line {index}: an approved Employee Tax Profile is required for Progressive Tax component {item.component_code}.")
                    if tax_profile.get("tax_exempt"): component_data["tax_bands"]=[{"lower_limit":0,"upper_limit":None,"rate":0}]
                    else:
                        rule_name=tax_profile.get("tax_rule") or getattr(item,"tax_rule",None)
                        if not rule_name: throw(f"Payroll line {index}: no Tax Rule is configured for {item.component_code}.")
                        if rule_name in seen_tax_rules: throw(f"Payroll line {index}: more than one Progressive Tax component uses Tax Rule {rule_name}; duplicate tax calculation is blocked.")
                        seen_tax_rules.add(rule_name)
                        rule=get_doc("Payroll Tax Rule",rule_name,ignore_permissions=True)
                        if rule.docstatus!=1 or rule.approval_status!="Approved" or str(rule.effective_from)>str(self.period_start) or (rule.effective_to and str(rule.effective_to)<str(self.period_end)):
                            throw(f"Payroll line {index}: tax rule {rule_name} is not approved and effective for this payroll period.")
                        if rule.jurisdiction!=tax_profile.get("jurisdiction"): throw(f"Payroll line {index}: Employee Tax Profile and Tax Rule jurisdictions differ.")
                        component_data["tax_rule"]=rule.name; component_data["tax_bands"]=[{"lower_limit":x.lower_limit,"upper_limit":x.upper_limit,"rate":x.rate} for x in rule.bands]
                        component_data["annual_relief"]=tax_profile.get("annual_relief") if tax_profile.get("annual_relief") not in (None,"") else (rule.annual_relief or item.annual_relief or 0)
                        component_data["tax_calculation_basis"]=rule.calculation_basis
                        frequency_periods={"Weekly":52,"Biweekly":26,"Fortnightly":26,"Semi-monthly":24,"Twice Monthly":24,"Monthly":12,"Quarterly":4,"Annual":1,"Annually":1}
                        component_data["periods_per_year"]=getattr(item,"periods_per_year",None) or frequency_periods.get(self.pay_frequency,12)
                        component_data["rounding_precision"]=int(rule.rounding_precision or 2)
                        component_data["tax_liability_account"]=getattr(item,"account",None) or item.credit_account
                        if rule.calculation_basis=="Cumulative YTD":
                            if tax_profile.get("tax_exempt"):
                                component_data["tax_calculation_basis"]="Annualised Period Income"
                                component_data["tax_bands"]=[{"lower_limit":0,"upper_limit":None,"rate":0}]
                            else:
                                ytd=_prior_payroll_tax_context(line.employee,item.component_code,rule.name,
                                    tax_profile.get("jurisdiction"),self.period_start,self.period_end,component_data["periods_per_year"],self.pay_frequency)
                                component_data.update(ytd)
                                _account(component_data.get("tax_liability_account"),["Liability"])
                components.append(component_data)
            # Recovery allocations are explicit employee-finance references; a payroll
            # deduction cannot silently reduce a loan or advance without a linked balance.
            loan_allocations=line.loan_recovery_allocations or []
            advance_allocations=line.advance_recovery_allocations or []
            if isinstance(loan_allocations,str): loan_allocations=json.loads(loan_allocations or "[]")
            if isinstance(advance_allocations,str): advance_allocations=json.loads(advance_allocations or "[]")
            if not isinstance(loan_allocations,list) or not isinstance(advance_allocations,list):
                throw(f"Payroll line {index}: loan and advance recovery allocations must be arrays.")
            auto_loan_allocations=not bool(loan_allocations)
            if auto_loan_allocations:
                active_loans=get_list("Employee Loan",filters=[["employee","=",line.employee],["docstatus","=",1]],fields=["name","loan_type","loan_account","outstanding_principal","status"],limit=10000,ignore_permissions=True)
                for loan_row in active_loans:
                    if loan_row.get("status") in ("Settled","Written Off") or not loan_row.get("loan_type"): continue
                    policy=get_doc("Employee Loan Type",loan_row["loan_type"],ignore_permissions=True)
                    if policy.recovery_method not in ("Payroll Deduction","Either"): continue
                    loan_doc=get_doc("Employee Loan",loan_row["name"],ignore_permissions=True)
                    due_principal=sum((D(x.principal_amount)-D(getattr(x,"paid_principal",0) or 0) for x in loan_doc.schedule if str(x.due_date)<=str(self.period_end)),ZERO)
                    due_interest=sum((D(x.interest_amount)-D(getattr(x,"paid_interest",0) or 0) for x in loan_doc.schedule if str(x.due_date)<=str(self.period_end)),ZERO)
                    if due_principal or due_interest:
                        loan_allocations.append({"employee_loan":loan_doc.name,"amount":str(money(due_principal)),"interest_amount":str(money(due_interest))})
            line.loan_recovery_allocations=_json_safe(loan_allocations)
            line.advance_recovery_allocations=_json_safe(advance_allocations)
            loan_total=ZERO; loan_interest_total=ZERO; advance_total=ZERO
            loan_totals_by_account={}; loan_interest_by_account={}; advance_totals_by_account={}
            loan_refs=set(); advance_refs=set()
            for allocation in loan_allocations:
                if allocation.get("employee_loan") in loan_refs: throw(f"Payroll line {index}: duplicate employee loan recovery allocation.")
                loan_refs.add(allocation.get("employee_loan"))
                loan=get_doc("Employee Loan",allocation.get("employee_loan"),ignore_permissions=True)
                allocation["loan_type"]=loan.loan_type
                allocation["loan_account"]=loan.loan_account
                allocation["interest_income_account"]=getattr(loan,"interest_income_account",None)
                due_dates=[str(x.due_date) for x in loan.schedule if str(x.due_date)<=str(self.period_end) and (D(x.principal_amount)-D(getattr(x,"paid_principal",0) or 0)>0 or D(x.interest_amount)-D(getattr(x,"paid_interest",0) or 0)>0)]
                allocation["due_date"]=min(due_dates) if due_dates else "9999-12-31"
                allocation["outstanding_principal"]=str(loan.outstanding_principal or 0)
                amount=money(allocation.get("amount")); interest_amount=money(allocation.get("interest_amount",0))
                if loan.docstatus!=1 or loan.employee!=line.employee or amount<=0 or amount>D(loan.outstanding_principal):
                    throw(f"Payroll line {index}: invalid loan recovery allocation {allocation.get('employee_loan')}.")
                if not any(x["component_type"]=="Loan Repayment" and x["credit_account"]==loan.loan_account for x in components):
                    throw(f"Payroll line {index}: add a Loan Repayment component mapped to {loan.loan_account}.")
                due_principal=sum((D(x.principal_amount)-D(getattr(x,"paid_principal",0) or 0) for x in loan.schedule if str(x.due_date)<=str(self.period_end)),ZERO)
                due_interest=sum((D(x.interest_amount)-D(getattr(x,"paid_interest",0) or 0) for x in loan.schedule if str(x.due_date)<=str(self.period_end)),ZERO)
                if amount>due_principal: throw(f"Payroll line {index}: principal recovery exceeds the loan instalments due by period end.")
                if interest_amount>due_interest: throw(f"Payroll line {index}: interest recovery exceeds the loan instalments due by period end.")
                if interest_amount:
                    interest_account=getattr(loan,"interest_income_account",None)
                    if not interest_account: throw(f"Payroll line {index}: loan {loan.name} has no Interest Income Account configured.")
                    if not any(x["component_type"]=="Loan Interest Recovery" and x["credit_account"]==interest_account for x in components):
                        throw(f"Payroll line {index}: add a Loan Interest Recovery component mapped to {interest_account}.")
                    if not any(money(D(x.interest_amount)-D(getattr(x,"paid_interest",0) or 0))>=interest_amount for x in loan.schedule):
                        throw(f"Payroll line {index}: interest recovery exceeds any single scheduled interest amount; split it by instalment.")
                loan_total+=amount; loan_interest_total+=interest_amount
                loan_totals_by_account[loan.loan_account]=loan_totals_by_account.get(loan.loan_account,ZERO)+amount
                if interest_amount: loan_interest_by_account[loan.interest_income_account]=loan_interest_by_account.get(loan.interest_income_account,ZERO)+interest_amount
            for allocation in advance_allocations:
                if allocation.get("employee_advance") in advance_refs: throw(f"Payroll line {index}: duplicate employee advance recovery allocation.")
                advance_refs.add(allocation.get("employee_advance"))
                advance=get_doc("Employee Advance",allocation.get("employee_advance"),ignore_permissions=True)
                amount=money(allocation.get("amount"))
                if advance.recovery_method!="Payroll Deduction": throw(f"Payroll line {index}: employee advance {advance.name} is not configured for payroll deduction.")
                if advance.docstatus!=1 or advance.employee!=line.employee or amount<=0 or amount>D(advance.outstanding_amount):
                    throw(f"Payroll line {index}: invalid advance recovery allocation {allocation.get('employee_advance')}.")
                if not any(x["component_type"]=="Advance Recovery" and x["credit_account"]==advance.advance_account for x in components):
                    throw(f"Payroll line {index}: add an Advance Recovery component mapped to {advance.advance_account}.")
                advance_total+=amount
                advance_totals_by_account[advance.advance_account]=advance_totals_by_account.get(advance.advance_account,ZERO)+amount
            # Scheduled loan components derive their values from the approved repayment schedules.
            principal_by_type={}; interest_by_type={}
            for allocation in loan_allocations:
                loan_doc=get_doc("Employee Loan",allocation["employee_loan"],ignore_permissions=True)
                if not loan_doc.loan_type: continue
                principal_by_type[loan_doc.loan_type]=principal_by_type.get(loan_doc.loan_type,ZERO)+money(allocation.get("amount",0))
                interest_by_type[loan_doc.loan_type]=interest_by_type.get(loan_doc.loan_type,ZERO)+money(allocation.get("interest_amount",0))
            for component in components:
                if component.get("calculation_type")=="Scheduled Loan Deduction":
                    component["scheduled_amount"]=money(principal_by_type.get(component.get("loan_type"),ZERO))
                elif component.get("calculation_type")=="Scheduled Loan Interest":
                    component["scheduled_amount"]=money(interest_by_type.get(component.get("loan_type"),ZERO))
            try:
                line_inputs=line.input_values or {}
                if isinstance(line_inputs,str): line_inputs=json.loads(line_inputs or "{}")
                line_inputs=dict(line_inputs)
                inputs={}
                payroll_input_refs=[]
                approved_inputs=get_list("Payroll Input",filters=[["employee","=",line.employee],["docstatus","=",1],["status","=","Active"]],fields=["name","salary_component","input_fieldname","input_value","effective_from","effective_to","input_frequency","input_mode","processed_payroll_run"],limit=10000,ignore_permissions=True)
                for payroll_input in approved_inputs:
                    if str(payroll_input.get("effective_from"))>str(self.period_end) or (payroll_input.get("effective_to") and str(payroll_input.get("effective_to"))<str(self.period_start)): continue
                    if payroll_input.get("input_frequency")=="One-time" and payroll_input.get("processed_payroll_run"): continue
                    field=payroll_input["input_fieldname"]
                    if field in inputs and payroll_input.get("input_mode")=="Replace": throw(f"Payroll line {index}: duplicate Replace inputs target {field}; resolve the conflicting payroll input records.")
                    value=Decimal(str(payroll_input.get("input_value") or 0))
                    if payroll_input.get("input_mode")=="Add": inputs[field]=Decimal(str(inputs.get(field,0) or 0))+value
                    else: inputs[field]=value
                    payroll_input_refs.append(payroll_input["name"])
                # Employee-level Payroll Run values override bulk inputs; individual Salary Slip values override both.
                inputs.update(line_inputs)
                existing_slip=None
                if getattr(line,"salary_slip",None):
                    try: existing_slip=get_doc("Salary Slip",line.salary_slip,ignore_permissions=True)
                    except Exception: existing_slip=None
                for rule in structure.components:
                    fieldname=getattr(rule,"input_fieldname",None)
                    if fieldname and existing_slip is not None:
                        variable_values=getattr(existing_slip,"variable_inputs",{}) or {}
                        if isinstance(variable_values,str): variable_values=json.loads(variable_values or "{}")
                        value=variable_values.get(fieldname,getattr(existing_slip,fieldname,None))
                        if value not in (None,""):
                            inputs[fieldname]=value
                            inputs[rule.component_code]=value
                        else:
                            if getattr(rule,"input_required",False): throw(f"Payroll line {index}: required Salary Slip input {fieldname} is missing.")
                            inputs.setdefault(fieldname,getattr(rule,"input_default",0) or 0)
                            inputs.setdefault(rule.component_code,getattr(rule,"input_default",0) or 0)
                    elif fieldname:
                        inputs.setdefault(fieldname,getattr(rule,"input_default",0) or 0)
                        inputs.setdefault(rule.component_code,getattr(rule,"input_default",0) or 0)
                inputs=_json_safe(inputs)
                line.input_values=inputs; line.payroll_input_refs=payroll_input_refs
                service_months=0
                if getattr(employee,"date_of_joining",None):
                    joined=date.fromisoformat(str(employee.date_of_joining)[:10]); period_end=date.fromisoformat(str(self.period_end)[:10])
                    service_months=max(0,(period_end.year-joined.year)*12+period_end.month-joined.month-(period_end.day<joined.day))
                employee_context={"employee_type":employee.employee_type or "Other","department":employee.department or "","designation":getattr(employee,"designation","") or "","branch":getattr(employee,"branch","") or "","grade":getattr(employee,"grade","") or "","service_months":service_months}
                calc_args={"base_salary":assignment.base_salary,"inputs":inputs,"employee_context":employee_context,"days_worked":line.days_worked if line.days_worked not in (None,"") else None,"days_in_period":line.days_in_period if line.days_in_period not in (None,"") else None,"overtime_hours":line.overtime_hours or 0}
                # First calculate net pay before any loan principal/interest recovery. This
                # baseline includes tax, ordinary deductions and any approved advance recovery.
                baseline_components=[dict(x) for x in components]
                for c in baseline_components:
                    if c.get("calculation_type") in ("Scheduled Loan Deduction","Scheduled Loan Interest"): c["scheduled_amount"]=0
                baseline=calculate_payroll(components=baseline_components,**calc_args)
                settings_rows=get_list("Finance Settings",fields=["maximum_loan_deduction_percent_of_net_pay","minimum_net_pay_after_loan_deductions","loan_recovery_allocation_method","allow_partial_loan_recovery"],limit=1,ignore_permissions=True)
                settings=settings_rows[0] if settings_rows else {}
                overall_percent=settings.get("maximum_loan_deduction_percent_of_net_pay")
                if overall_percent in (None, ""): overall_percent=30
                minimum_net=settings.get("minimum_net_pay_after_loan_deductions")
                if minimum_net in (None, ""): minimum_net=0
                allocation_method=settings.get("loan_recovery_allocation_method") or "Oldest Due First"
                partial_setting=settings.get("allow_partial_loan_recovery")
                allow_partial=True if partial_setting in (None, "") else bool(partial_setting)
                loan_type_policies={}
                for allocation in loan_allocations:
                    loan_type=allocation.get("loan_type")
                    if loan_type and loan_type not in loan_type_policies:
                        policy_doc=get_doc("Employee Loan Type",loan_type,ignore_permissions=True)
                        loan_type_policies[loan_type]={"maximum_deduction_percent_of_net_pay":getattr(policy_doc,"maximum_deduction_percent_of_net_pay",0) or 0,"deduction_priority":getattr(policy_doc,"deduction_priority",100) or 100,"allow_partial_recovery":(True if getattr(policy_doc,"allow_partial_recovery",None) in (None, "") else bool(policy_doc.allow_partial_recovery)),"allocation_method":(getattr(policy_doc,"allocation_method",None) if getattr(policy_doc,"allocation_method",None)!="Use Finance Default" else None)}
                capped=allocate_loan_recoveries(loan_allocations,net_before_loan_recovery=baseline["net_pay"],overall_percent=overall_percent,minimum_net_pay=minimum_net,loan_type_policies=loan_type_policies,allocation_method=allocation_method,allow_partial=allow_partial)
                loan_allocations=capped["allocations"]
                line.loan_recovery_allocations=_json_safe(loan_allocations)
                # Rebuild exact account totals from the capped allocations. No loan schedule
                # is mutated during calculation; the snapshot is committed only at posting.
                loan_totals_by_account={}; loan_interest_by_account={}; principal_by_type={}; interest_by_type={}
                for allocation in loan_allocations:
                    loan_doc=get_doc("Employee Loan",allocation["employee_loan"],ignore_permissions=True)
                    principal=money(allocation.get("amount",0)); interest=money(allocation.get("interest_amount",0))
                    if principal: loan_totals_by_account[loan_doc.loan_account]=loan_totals_by_account.get(loan_doc.loan_account,ZERO)+principal
                    if interest: loan_interest_by_account[loan_doc.interest_income_account]=loan_interest_by_account.get(loan_doc.interest_income_account,ZERO)+interest
                    if loan_doc.loan_type:
                        principal_by_type[loan_doc.loan_type]=principal_by_type.get(loan_doc.loan_type,ZERO)+principal
                        interest_by_type[loan_doc.loan_type]=interest_by_type.get(loan_doc.loan_type,ZERO)+interest
                for component in components:
                    if component.get("calculation_type")=="Scheduled Loan Deduction": component["scheduled_amount"]=money(principal_by_type.get(component.get("loan_type"),ZERO))
                    elif component.get("calculation_type")=="Scheduled Loan Interest": component["scheduled_amount"]=money(interest_by_type.get(component.get("loan_type"),ZERO))
                result=calculate_payroll(components=components,**calc_args)
                approved_tax_credit=ZERO
                for tax_row in result.get("tax_computation",[]):
                    credit=money(tax_row.get("refund_credit_amount",0))
                    if credit>0:
                        review=_approved_tax_credit_review(self.name,line.employee,tax_row) if self.name else None
                        if review:
                            tax_row["approved_credit_amount"]=str(credit)
                            tax_row["credit_review_reference"]=review["name"]
                            approved_tax_credit+=credit
                if approved_tax_credit:
                    result["net_pay"]=money(result["net_pay"]+approved_tax_credit)
                if money(result["net_pay"])<money(minimum_net) and capped["allowed_total"]>0:
                    throw(f"Payroll line {index}: loan recovery would breach the configured minimum net pay.")
                line.loan_recovery_summary=_json_safe(capped)
            except (PayrollCalculationError,ValueError,TypeError) as exc: throw(f"Payroll line {index} ({line.employee}): {exc}")
            calculated_loan={}; calculated_interest={}; calculated_advance={}
            for calculated in result["lines"]:
                kind=calculated["component_type"]; account=calculated.get("credit_account")
                if kind=="Loan Repayment": calculated_loan[account]=calculated_loan.get(account,ZERO)+money(calculated["amount"])
                elif kind=="Loan Interest Recovery": calculated_interest[account]=calculated_interest.get(account,ZERO)+money(calculated["amount"])
                elif kind=="Advance Recovery": calculated_advance[account]=calculated_advance.get(account,ZERO)+money(calculated["amount"])
            if {k:money(v) for k,v in loan_totals_by_account.items()}!={k:money(v) for k,v in calculated_loan.items()}:
                throw(f"Payroll line {index}: Loan Repayment components must exactly match linked loan recoveries by receivable account.")
            if {k:money(v) for k,v in loan_interest_by_account.items()}!={k:money(v) for k,v in calculated_interest.items()}:
                throw(f"Payroll line {index}: Loan Interest Recovery components must exactly match linked loan interest by income account.")
            if {k:money(v) for k,v in advance_totals_by_account.items()}!={k:money(v) for k,v in calculated_advance.items()}:
                throw(f"Payroll line {index}: Advance Recovery components must exactly match linked advance recoveries by receivable account.")
            line.base_salary=assignment.base_salary; line.calculation_lines=_json_safe(result["lines"]); line.gross_earnings=result["gross_earnings"]; line.employee_deductions=result["employee_deductions"]; line.loan_repayments=result["loan_repayments"]; line.advance_recoveries=result["advance_recoveries"]; line.employer_contributions=result["employer_contributions"]; line.net_pay=result["net_pay"]; line.total_employer_cost=result["total_employer_cost"]; line.tax_computation=_json_safe(result.get("tax_computation",[])); line.tax_credit_amount=money(approved_tax_credit)
            totals["gross"]+=result["gross_earnings"]; totals["deductions"]+=result["total_deductions"]; totals["employer"]+=result["employer_contributions"]; totals["net"]+=result["net_pay"]; totals["cost"]+=result["total_employer_cost"]
            fingerprint_rows.append({"employee":line.employee,"assignment":line.salary_assignment,"result":{k:str(v) for k,v in result.items() if k!="lines"},"lines":[{k:str(v) for k,v in x.items()} for x in result["lines"]],"loan_allocations":loan_allocations,"advance_allocations":advance_allocations,"tax_computation":result.get("tax_computation",[]),"tax_credit_amount":str(approved_tax_credit),"payroll_input_refs":payroll_input_refs,"inputs":inputs})
        self.total_employees=len(seen); self.total_gross=money(totals["gross"]); self.total_deductions=money(totals["deductions"]); self.total_employer_contributions=money(totals["employer"]); self.total_net_pay=money(totals["net"]); self.total_employer_cost=money(totals["cost"])
        fingerprint=_fingerprint({"title":self.run_title,"frequency":self.pay_frequency,"start":str(self.period_start),"end":str(self.period_end),"posting_date":str(self.posting_date),"currency":self.currency,"payable":self.payroll_payable_account,"employees":fingerprint_rows})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved payroll calculations are immutable. Reset approval and obtain a new approval decision before changing inputs.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
        self.status={"Pending":"Pending Approval","Approved":"Approved","Rejected":"Rejected"}.get(self.approval_status,"Draft")
    def after_insert(self):
        # Create editable draft slips so period-specific inputs can be entered per employee.
        for line in self.employees:
            if getattr(line,"salary_slip",None): continue
            slip=new_doc("Salary Slip",employee=line.employee,payroll_run=self.name,salary_assignment=line.salary_assignment,
                period_start=self.period_start,period_end=self.period_end,currency=self.currency,
                payroll_payable_account=self.payroll_payable_account,variable_inputs={},input_status="Pending",status="Draft",
                loan_recovery_allocations=line.loan_recovery_allocations or [],loan_recovery_summary=getattr(line,"loan_recovery_summary",None),
                advance_recovery_allocations=line.advance_recovery_allocations or [],gross_earnings=line.gross_earnings,
                employee_deductions=line.employee_deductions,loan_repayments=line.loan_repayments,
                advance_recoveries=line.advance_recoveries,employer_contributions=line.employer_contributions,
                net_pay=line.net_pay,total_employer_cost=line.total_employer_cost,tax_computation=line.tax_computation or [],tax_credit_amount=getattr(line,"tax_credit_amount",0) or 0,
                lines=[{"component_code":x["component_code"],"component_name":x["component_name"],"component_type":x["component_type"],"amount":x["amount"],"taxable":x.get("taxable"),"pensionable":x.get("pensionable"),"hide_on_payslip":1 if x.get("hide_on_payslip") else 0,"debit_account":x.get("debit_account"),"credit_account":x.get("credit_account"),"cost_centre":x.get("cost_centre"),"business_unit":x.get("business_unit")} for x in line.calculation_lines])
            slip.flags.trusted_source=True; slip.insert(ignore_permissions=True)
            line.salary_slip=slip.name
            if line.name: db_update_child("Payroll Run Employee",line.name,salary_slip=slip.name)
        _sync_tax_credit_reviews(self)
    def on_update(self):
        # A preparer can enter a Salary Slip variable field, save the slip, then save
        # the Payroll Run. The recalculated Earnings/Deductions and recovery cap are
        # reflected back onto each still-draft slip without touching the entered fields.
        if self.docstatus==1: return
        for line in self.employees:
            if not getattr(line,"salary_slip",None): continue
            try: slip=get_doc("Salary Slip",line.salary_slip,ignore_permissions=True)
            except Exception: continue
            if slip.docstatus!=0: continue
            slip.loan_recovery_allocations=line.loan_recovery_allocations or []
            slip.loan_recovery_summary=getattr(line,"loan_recovery_summary",None)
            slip.advance_recovery_allocations=line.advance_recovery_allocations or []
            slip.gross_earnings=line.gross_earnings; slip.employee_deductions=line.employee_deductions
            slip.loan_repayments=line.loan_repayments; slip.advance_recoveries=line.advance_recoveries
            slip.employer_contributions=line.employer_contributions; slip.net_pay=line.net_pay
            slip.total_employer_cost=line.total_employer_cost; slip.tax_computation=line.tax_computation or []; slip.tax_credit_amount=getattr(line,"tax_credit_amount",0) or 0
            slip.set("lines",[{"component_code":x["component_code"],"component_name":x["component_name"],"component_type":x["component_type"],"amount":x["amount"],"taxable":x.get("taxable"),"pensionable":x.get("pensionable"),"hide_on_payslip":1 if x.get("hide_on_payslip") else 0,"debit_account":x.get("debit_account"),"credit_account":x.get("credit_account"),"cost_centre":x.get("cost_centre"),"business_unit":x.get("business_unit")} for x in line.calculation_lines])
            slip.flags.trusted_source=True; slip.save(ignore_permissions=True)
        _sync_tax_credit_reviews(self)
    def before_submit(self):
        _approved(self)
        for line in self.employees:
            for tax_row in _as_rows(getattr(line,"tax_computation",None)):
                if money(tax_row.get("refund_credit_amount",0))>0:
                    review=_approved_tax_credit_review(self.name,line.employee,tax_row)
                    if not review:
                        throw(f"Employee {line.employee}: PAYE refund/credit of {tax_row.get('refund_credit_amount')} requires an independently approved Tax Refund Credit Review before payroll posting.")
        if not self.approval_hash: throw("Independent approval is required before posting payroll.")
    def on_submit(self):
        posting=[]; prepared=[]
        for line in self.employees:
            result={"lines":line.calculation_lines,"net_pay":money(line.net_pay)}
            assignment=get_doc("Salary Structure Assignment",line.salary_assignment,ignore_permissions=True)
            employee=get_doc("Employee",line.employee,ignore_permissions=True)
            structure=get_doc("Salary Structure",assignment.salary_structure,ignore_permissions=True)
            posting.extend(payroll_posting_lines(employee=line.employee,result=result,payroll_payable_account=self.payroll_payable_account,cost_centre=getattr(line,"cost_centre",None) or assignment.cost_centre or getattr(employee,"default_cost_centre",None) or getattr(structure,"default_cost_centre",None) or self.cost_centre,business_unit=getattr(line,"business_unit",None) or getattr(assignment,"business_unit",None) or getattr(employee,"default_business_unit",None) or getattr(structure,"default_business_unit",None)))
            for tax_row in _as_rows(getattr(line,"tax_computation",None)):
                credit=money(tax_row.get("approved_credit_amount",0))
                if credit:
                    posting.append({"account":tax_row.get("tax_liability_account"),"debit":credit,"credit":0,
                        "line_description":f"Approved PAYE refund credit — {line.employee} — {tax_row.get('component_code')}"})
            prepared.append((line,assignment))
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.posting_date,currency=self.currency,exchange_rate=1,lines=posting,posting_event="Original",remarks=f"Approved payroll {self.run_title}",idempotency_key=f"payroll-run:{self.name}")
        for line,assignment in prepared:
            for tax_row in _as_rows(getattr(line,"tax_computation",None)):
                review_name=tax_row.get("credit_review_reference")
                if review_name and money(tax_row.get("approved_credit_amount",0))>0:
                    review_doc=get_doc("Tax Refund Credit Review",review_name,ignore_permissions=True)
                    db_update(review_doc,status="Applied",posting_batch=batch.name,applied_on=datetime.now(timezone.utc).replace(tzinfo=None))
        for line,assignment in prepared:
            slip=get_doc("Salary Slip",line.salary_slip,ignore_permissions=True) if getattr(line,"salary_slip",None) else new_doc("Salary Slip")
            slip.employee=line.employee; slip.payroll_run=self.name; slip.salary_assignment=line.salary_assignment
            slip.period_start=self.period_start; slip.period_end=self.period_end; slip.currency=self.currency; slip.payroll_payable_account=self.payroll_payable_account
            slip.loan_recovery_allocations=line.loan_recovery_allocations or []; slip.loan_recovery_summary=getattr(line,"loan_recovery_summary",None); slip.advance_recovery_allocations=line.advance_recovery_allocations or []
            slip.set("lines",[{"component_code":x["component_code"],"component_name":x["component_name"],"component_type":x["component_type"],"amount":x["amount"],"taxable":x.get("taxable"),"pensionable":x.get("pensionable"),"hide_on_payslip":1 if x.get("hide_on_payslip") else 0,"debit_account":x.get("debit_account"),"credit_account":x.get("credit_account"),"cost_centre":x.get("cost_centre"),"business_unit":x.get("business_unit")} for x in line.calculation_lines])
            slip.tax_computation=line.tax_computation or []; slip.tax_credit_amount=getattr(line,"tax_credit_amount",0) or 0; slip.gross_earnings=line.gross_earnings; slip.employee_deductions=line.employee_deductions; slip.loan_repayments=line.loan_repayments; slip.advance_recoveries=line.advance_recoveries; slip.employer_contributions=line.employer_contributions; slip.net_pay=line.net_pay; slip.total_employer_cost=line.total_employer_cost
            slip.posting_batch=batch.name; slip.paid_amount=0; slip.outstanding_amount=line.net_pay; slip.status="Posted"; slip.input_status="Complete"
            slip.flags.trusted_source=True
            if slip.is_new(): slip.insert(ignore_permissions=True)
            else: slip.save(ignore_permissions=True)
            slip.submit(ignore_permissions=True)
            for input_name in (line.payroll_input_refs or []):
                payroll_input=get_doc("Payroll Input",input_name,ignore_permissions=True)
                if payroll_input.input_frequency=="One-time": db_update(payroll_input,status="Processed",processed_payroll_run=self.name)
            for allocation in (line.loan_recovery_allocations or []):
                loan=get_doc("Employee Loan",allocation["employee_loan"],ignore_permissions=True)
                principal=money(allocation["amount"]); interest=money(allocation.get("interest_amount",0))
                apply_loan_schedule_recovery(loan,principal_amount=principal,interest_amount=interest,paid_on=self.period_end)
                remaining=money(D(loan.outstanding_principal)-principal)
                db_update(loan,outstanding_principal=remaining,status="Settled" if remaining==0 else "Disbursed")
            for allocation in (line.advance_recovery_allocations or []):
                advance=get_doc("Employee Advance",allocation["employee_advance"],ignore_permissions=True)
                remaining=money(D(advance.outstanding_amount)-D(allocation["amount"]))
                db_update(advance,outstanding_amount=remaining,status="Settled" if remaining==0 else "Partially Settled")
        db_update(self,posting_batch=batch.name,status="Posted")

class PayrollPayment(Document):
    def validate(self):
        _approval(self)
        if not self.payment_date or not self.currency or not self.lines: throw("Payment Date, Currency and at least one payment line are required.")
        total=ZERO; seen=set(); references=set()
        for index,line in enumerate(self.lines,1):
            if line.salary_slip in seen: throw("A Salary Slip may appear only once in a Payroll Payment.")
            seen.add(line.salary_slip)
            slip=get_doc("Salary Slip",line.salary_slip,ignore_permissions=True)
            if slip.docstatus!=1 or slip.currency!=self.currency: throw(f"Payment line {index}: select a posted Salary Slip in the same currency.")
            amount=money(line.amount)
            calculated_outstanding=money(D(slip.net_pay)-D(getattr(slip,"paid_amount",0) or 0))
            stored_outstanding=money(getattr(slip,"outstanding_amount",calculated_outstanding) or 0)
            if calculated_outstanding<0 or stored_outstanding!=calculated_outstanding:
                throw(f"Payment line {index}: Salary Slip paid/outstanding balances are inconsistent; reconcile the slip before payment.")
            if amount<=0 or amount>calculated_outstanding: throw(f"Payment line {index}: amount must be positive and cannot exceed the outstanding salary payable.")
            bank_meta=_account(line.bank_account,["Asset"])
            if bank_meta.get("account_currency") and bank_meta.get("account_currency")!=self.currency:
                throw(f"Payment line {index}: bank account currency differs from Payroll Payment currency.")
            bank_ref=str(getattr(line,"reference",None) or "").strip()
            if bank_ref:
                ref_key=(line.bank_account,bank_ref.casefold())
                if ref_key in references: throw(f"Payment line {index}: duplicate bank reference for the same bank account.")
                references.add(ref_key)
            payable=_account(slip.payroll_payable_account,["Liability"],party=True)
            line.employee=slip.employee; total+=amount
        self.total_amount=money(total)
        fingerprint=_fingerprint({"date":str(self.payment_date),"currency":self.currency,"lines":[{"slip":x.salary_slip,"amount":str(x.amount),"bank":x.bank_account,"reference":getattr(x,"reference",None),"employee":x.employee} for x in self.lines]})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved payroll payments are immutable; reset approval before changing settlement instructions.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self):
        self.validate()
        _approved(self)
    def on_submit(self):
        lines=[]
        for item in self.lines:
            slip=get_doc("Salary Slip",item.salary_slip,ignore_permissions=True); amount=money(item.amount)
            lines.extend([{"account":slip.payroll_payable_account,"debit":amount,"credit":0,"party_type":"Employee","party":slip.employee,"line_description":f"Salary settlement {slip.employee} — {slip.name}"},{"account":item.bank_account,"debit":0,"credit":amount,"line_description":f"Salary payment {slip.employee} — {slip.name}"}])
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.payment_date,currency=self.currency,exchange_rate=1,lines=lines,posting_event="Original",remarks=self.remarks or f"Payroll payment {self.name}",idempotency_key=f"payroll-payment:{self.name}")
        for item in self.lines:
            slip=get_doc("Salary Slip",item.salary_slip,ignore_permissions=True); paid=money(D(slip.paid_amount)+D(item.amount)); outstanding=money(D(slip.net_pay)-paid)
            db_update(slip,paid_amount=paid,outstanding_amount=outstanding,status="Paid" if outstanding==0 else "Partially Paid")
        db_update(self,posting_batch=batch.name,status="Posted")

class EmployeeLoan(Document):
    def validate(self):
        _approval(self)
        if not all((self.employee,self.loan_date,self.first_repayment_date,self.loan_account,self.bank_account,self.currency)): throw("Employee, dates, accounts and currency are required.")
        if D(self.principal_amount)<=0 or int(self.term_months or 0)<=0: throw("Loan principal and term must be positive.")
        _account(self.loan_account,["Asset"],party=True); _account(self.bank_account,["Asset"])
        if D(self.annual_interest_rate)>0 and not self.interest_income_account: throw("An Interest Income Account is required when the employee loan charges interest.")
        if self.interest_income_account: _account(self.interest_income_account,["Income"])
        employee=get_doc("Employee",self.employee,ignore_permissions=True)
        if employee.disabled: throw("A disabled employee cannot receive a loan.")
        if str(self.first_repayment_date)<=str(self.loan_date): throw("First repayment date must be after the loan date.")
        try: schedule=loan_schedule(principal=self.principal_amount,annual_rate=self.annual_interest_rate or 0,months=self.term_months,first_date=self.first_repayment_date,method=self.repayment_method)
        except ValueError as exc: throw(str(exc))
        self.schedule=[]
        for schedule_line in schedule:
            schedule_line["due_date"]=date.fromisoformat(schedule_line["due_date"])
            self.append("schedule",schedule_line)
        self._link_children()
        self.total_interest=money(sum((D(x["interest_amount"]) for x in schedule),ZERO)); self.total_repayment=money(sum((D(x["total_due"]) for x in schedule),ZERO)); self.outstanding_principal=money(self.principal_amount)
        fingerprint=_fingerprint({"employee":self.employee,"date":str(self.loan_date),"principal":str(self.principal_amount),"rate":str(self.annual_interest_rate),"term":self.term_months,"method":self.repayment_method,"schedule":[{k:str(v) for k,v in x.items()} for x in schedule],"loan_account":self.loan_account,"bank":self.bank_account})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved employee loans are immutable; reset approval before changing terms.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self): _approved(self)
    def on_submit(self):
        amount=money(self.principal_amount)
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.loan_date,currency=self.currency,exchange_rate=1,lines=[{"account":self.loan_account,"debit":amount,"credit":0,"party_type":"Employee","party":self.employee,"line_description":f"Employee loan disbursement {self.name}"},{"account":self.bank_account,"debit":0,"credit":amount,"line_description":f"Employee loan disbursement {self.name}"}],posting_event="Original",remarks=f"Employee loan {self.name}",idempotency_key=f"employee-loan:{self.name}")
        db_update(self,posting_batch=batch.name,status="Disbursed",outstanding_principal=amount)
    def before_cancel(self):
        if D(self.outstanding_principal)!=D(self.principal_amount): throw("This loan has repayments or payroll recoveries. Cancel those first (or use Cancel All).")

class EmployeeLoanRepayment(Document):
    def validate(self):
        _approval(self)
        loan=get_doc("Employee Loan",self.employee_loan,ignore_permissions=True)
        self.interest_income_account=self.interest_income_account or getattr(loan,"interest_income_account",None)
        if loan.docstatus!=1 or loan.employee!=self.employee: throw("Select a disbursed loan belonging to the selected employee.")
        if self.currency!=loan.currency or self.loan_account!=loan.loan_account: throw("Repayment currency and loan account must match the original loan.")
        if D(self.principal_amount)<=0 or D(self.interest_amount)<0: throw("Principal repayment must be positive and interest cannot be negative.")
        if D(self.principal_amount)>D(loan.outstanding_principal): throw("Principal repayment exceeds outstanding loan principal.")
        if self.repayment_date and str(self.repayment_date)<str(loan.loan_date): throw("A repayment cannot be dated before the loan was disbursed.")
        if self.settlement_method=="Bank / Cash": _account(self.bank_account,["Asset"])
        elif self.settlement_method=="Payroll Deduction": _account(self.payroll_payable_account,["Liability"],party=True)
        else: throw("Select a valid loan repayment method.")
        if D(self.interest_amount): _account(self.interest_income_account,["Income"])
        fingerprint=_fingerprint({"loan":self.employee_loan,"employee":self.employee,"date":str(self.repayment_date),"principal":str(self.principal_amount),"interest":str(self.interest_amount),"method":self.settlement_method,"bank":self.bank_account or "","payable":self.payroll_payable_account or "","loan_account":self.loan_account,"interest_account":self.interest_income_account or ""})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved loan repayments are immutable; reset approval before changing the settlement.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self): _approved(self)
    def on_submit(self):
        loan=get_doc("Employee Loan",self.employee_loan,ignore_permissions=True); lines=[]
        # Serialise repayments of one loan: two drafts validated earlier cannot together recover more than the outstanding principal.
        loan._lock_and_check(); loan.reload()
        if D(self.principal_amount)>D(loan.outstanding_principal): throw(f"Principal repayment exceeds the loan's outstanding principal of {loan.outstanding_principal}.")
        debit=self.bank_account if self.settlement_method=="Bank / Cash" else self.payroll_payable_account
        lines.append({"account":debit,"debit":money(D(self.principal_amount)+D(self.interest_amount)),"credit":0,"party_type":"Employee" if self.settlement_method=="Payroll Deduction" else None,"party":self.employee if self.settlement_method=="Payroll Deduction" else None,"line_description":f"Employee loan repayment {self.name}"})
        lines.append({"account":self.loan_account,"debit":0,"credit":money(self.principal_amount),"party_type":"Employee","party":self.employee,"line_description":f"Employee loan principal repayment {self.name}"})
        if D(self.interest_amount): lines.append({"account":self.interest_income_account,"debit":0,"credit":money(self.interest_amount),"line_description":f"Employee loan interest {self.name}"})
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.repayment_date,currency=self.currency,exchange_rate=1,lines=lines,posting_event="Original",remarks=f"Employee loan repayment {self.name}",idempotency_key=f"employee-loan-repayment:{self.name}")
        apply_loan_schedule_recovery(loan,principal_amount=self.principal_amount,interest_amount=self.interest_amount,paid_on=self.repayment_date)
        remaining=money(D(loan.outstanding_principal)-D(self.principal_amount)); db_update(loan,outstanding_principal=remaining,status="Settled" if remaining==0 else "Disbursed")
        db_update(self,posting_batch=batch.name,status="Posted")

class EmployeeAdvance(Document):
    def validate(self):
        _approval(self)
        if not all((self.employee,self.advance_date,self.purpose,self.currency,self.advance_account,self.bank_account)) or D(self.amount)<=0: throw("Employee, date, purpose, positive amount, currency and accounts are required.")
        _account(self.advance_account,["Asset"],party=True); _account(self.bank_account,["Asset"])
        employee=get_doc("Employee",self.employee,ignore_permissions=True)
        if employee.disabled: throw("A disabled employee cannot receive an advance.")
        fingerprint=_fingerprint({"employee":self.employee,"date":str(self.advance_date),"purpose":self.purpose,"amount":str(self.amount),"currency":self.currency,"advance_account":self.advance_account,"bank":self.bank_account,"recovery":self.recovery_method})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved employee advances are immutable; reset approval before changing terms.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self): _approved(self)
    def on_submit(self):
        amount=money(self.amount); batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.advance_date,currency=self.currency,exchange_rate=1,lines=[{"account":self.advance_account,"debit":amount,"credit":0,"party_type":"Employee","party":self.employee,"line_description":f"Employee advance {self.name}"},{"account":self.bank_account,"debit":0,"credit":amount,"line_description":f"Employee advance disbursement {self.name}"}],posting_event="Original",remarks=self.purpose,idempotency_key=f"employee-advance:{self.name}")
        db_update(self,posting_batch=batch.name,status="Disbursed",outstanding_amount=amount)
    def before_cancel(self):
        if D(self.outstanding_amount)!=D(self.amount): throw("This advance has settlements or payroll recoveries. Cancel those first (or use Cancel All).")

class EmployeeAdvanceSettlement(Document):
    def validate(self):
        _approval(self)
        advance=get_doc("Employee Advance",self.employee_advance,ignore_permissions=True)
        if advance.docstatus!=1 or advance.employee!=self.employee: throw("Select a disbursed employee advance belonging to the selected employee.")
        if self.currency!=advance.currency or not self.lines: throw("Settlement currency must match the advance and at least one settlement line is required.")
        total=ZERO
        for line in self.lines:
            amount=money(line.amount)
            if amount<=0: throw("Settlement amounts must be positive.")
            account=_account(line.account,["Expense"] if line.settlement_type=="Expense Evidence" else ["Asset"])
            total+=amount
        if total>D(advance.outstanding_amount): throw("Settlement exceeds the outstanding employee advance.")
        if self.settlement_date and str(self.settlement_date)<str(advance.advance_date): throw("An advance cannot be settled before it was paid out.")
        self.total_amount=money(total)
        fingerprint=_fingerprint({"advance":self.employee_advance,"employee":self.employee,"date":str(self.settlement_date),"currency":self.currency,"lines":[{"type":x.settlement_type,"account":x.account,"amount":str(x.amount),"description":x.description or ""} for x in self.lines]})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved advance settlements are immutable; reset approval before changing the settlement.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self): _approved(self)
    def on_submit(self):
        advance=get_doc("Employee Advance",self.employee_advance,ignore_permissions=True); lines=[]
        # Serialise settlements of one advance: two drafts validated earlier cannot together settle more than is outstanding.
        advance._lock_and_check(); advance.reload()
        if D(self.total_amount)>D(advance.outstanding_amount): throw(f"Settlement exceeds the advance's outstanding balance of {advance.outstanding_amount}.")
        for item in self.lines:
            amount=money(item.amount)
            lines.append({"account":item.account,"debit":amount,"credit":0,"line_description":item.description or f"Employee advance settlement {self.name}"})
        lines.append({"account":advance.advance_account,"debit":0,"credit":money(self.total_amount),"party_type":"Employee","party":self.employee,"line_description":f"Employee advance settlement {self.name}"})
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.settlement_date,currency=self.currency,exchange_rate=1,lines=lines,posting_event="Original",remarks=f"Employee advance settlement {self.name}",idempotency_key=f"employee-advance-settlement:{self.name}")
        remaining=money(D(advance.outstanding_amount)-D(self.total_amount)); db_update(advance,outstanding_amount=remaining,status="Settled" if remaining==0 else "Partially Settled")
        db_update(self,posting_batch=batch.name,status="Posted")


def _sync_tax_credit_reviews(payroll_run):
    if not getattr(payroll_run,"name",None): return
    active=set()
    for line in payroll_run.employees or []:
        for tax_row in _as_rows(getattr(line,"tax_computation",None)):
            credit=money(tax_row.get("refund_credit_amount",0))
            if credit<=0: continue
            component_code=tax_row.get("component_code")
            fingerprint=_tax_credit_fingerprint(payroll_run.name,line.employee,tax_row)
            active.add((line.employee,component_code))
            rows=get_list("Tax Refund Credit Review",filters=[["payroll_run","=",payroll_run.name],
                ["employee","=",line.employee],["tax_component_code","=",component_code]],
                fields=["name"],limit=20,ignore_permissions=True)
            if len(rows)>1: throw(f"Duplicate Tax Refund Credit Review records exist for {line.employee}/{component_code}.")
            values={"payroll_run":payroll_run.name,"employee":line.employee,"salary_slip":getattr(line,"salary_slip",None),
                "tax_component_code":component_code,"tax_rule":tax_row.get("tax_rule"),
                "tax_year_start":tax_row.get("tax_year_start"),"currency":payroll_run.currency,
                "tax_liability_account":tax_row.get("tax_liability_account"),"proposed_credit_amount":credit,
                "source_calculation_fingerprint":fingerprint,"calculation_snapshot":tax_row}
            if rows:
                review=get_doc("Tax Refund Credit Review",rows[0]["name"],ignore_permissions=True)
                if review.approval_status=="Approved" and review.source_calculation_fingerprint==fingerprint and money(review.proposed_credit_amount)==credit:
                    continue   # an approved review whose source is unchanged is immutable (v1.4.0): re-saving it would raise and block the payroll run
                if review.approval_status=="Approved" and (review.source_calculation_fingerprint!=fingerprint or money(review.proposed_credit_amount)!=credit):
                    # Source changes automatically invalidate approval; the credit must be reviewed again.
                    review.approval_status="Pending"; review.approved_credit_amount=0
                    review.approval_hash=None; review.approved_by=None; review.approved_on=None
                    review.flags.system_approval_invalidation=True
                    from velora import workflows
                    workflows.reset_state(review,"Pending","The payroll tax calculation changed, so the earlier approval no longer applies")
                if review.status not in ("Applied",):
                    for key,value in values.items(): setattr(review,key,value)
                    from velora import workflows
                    with workflows.engine_write(): review.save(ignore_permissions=True)
            else:
                new_doc("Tax Refund Credit Review",**values,approval_status="Pending",status="Pending Review").insert(ignore_permissions=True)
    # Draft review items no longer supported by the current payroll calculation are superseded, never deleted.
    existing=get_list("Tax Refund Credit Review",filters=[["payroll_run","=",payroll_run.name]],fields=["name","employee","tax_component_code","approval_status","status"],limit=10000,ignore_permissions=True)
    for row_data in existing:
        if (row_data.get("employee"),row_data.get("tax_component_code")) not in active and row_data.get("status") not in ("Applied","Superseded"):
            review=get_doc("Tax Refund Credit Review",row_data["name"],ignore_permissions=True)
            db_update(review,status="Superseded")


class TaxRefundCreditReview(Document):
    def validate(self):
        old=getattr(self,"_old",None) or {}
        if old.get("status")=="Applied":
            throw("An applied PAYE refund/credit review is immutable and retained for audit.")
        if getattr(self.flags,"system_approval_invalidation",False):
            if old.get("approval_status")!="Approved" or self.approval_status!="Pending":
                throw("System approval invalidation is permitted only to reset a stale approved tax credit to Pending.")
        else:
            _approval(self)
        if not all((self.payroll_run,self.employee,self.tax_component_code,self.tax_rule,self.tax_year_start,self.currency,self.tax_liability_account,self.source_calculation_fingerprint)):
            throw("Payroll Run, Employee, Tax Component, Tax Rule, Tax Year, Currency, Tax Liability Account and source fingerprint are required.")
        credit=money(self.proposed_credit_amount)
        if credit<=0: throw("Proposed PAYE refund/credit must be greater than zero.")
        _account(self.tax_liability_account,["Liability"])
        run=get_doc("Payroll Run",self.payroll_run,ignore_permissions=True)
        if run.docstatus!=0 or run.currency!=self.currency:
            throw("Tax refund credits can only be reviewed against an unposted Payroll Run in the same currency.")
        matching=[line for line in run.employees or [] if line.employee==self.employee]
        if len(matching)!=1: throw("The Employee must appear exactly once in the source Payroll Run.")
        tax_rows=[x for x in _as_rows(getattr(matching[0],"tax_computation",None)) if x.get("component_code")==self.tax_component_code]
        if len(tax_rows)!=1: throw("The source Payroll Run no longer contains exactly one matching PAYE calculation.")
        tax_row=tax_rows[0]
        expected=_tax_credit_fingerprint(self.payroll_run,self.employee,tax_row)
        if expected!=self.source_calculation_fingerprint or money(tax_row.get("refund_credit_amount",0))!=credit:
            throw("The Tax Refund Credit Review does not match the current payroll tax calculation.")
        snapshot=_fingerprint({"source":expected,"amount":str(credit),"liability_account":self.tax_liability_account,"currency":self.currency})
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved":
            if old.get("approval_hash")!=snapshot or self.approval_hash!=snapshot:
                throw("An approved PAYE refund/credit review is immutable. Reset approval before changing its source or amount.")
        elif self.approval_status=="Approved":
            self.approved_credit_amount=credit; self.approval_hash=snapshot
        else:
            self.approved_credit_amount=0; self.approval_hash=None
        self.status={"Pending":"Pending Review","Approved":"Approved","Rejected":"Rejected"}.get(self.approval_status,"Pending Review")
    def before_delete(self):
        if self.approval_status=="Approved" or self.status=="Applied":
            throw("Approved or applied PAYE refund/credit reviews are retained for audit.")


class SalarySlip(Document):
    def before_insert(self):
        if not getattr(self.flags,"trusted_source",False):
            throw("Salary Slips can only be generated from a Payroll Run.")
    def validate(self):
        if self.docstatus==1 and not getattr(self.flags,"trusted_source",False):
            throw("Posted Salary Slips are immutable.")
        if self.payroll_run:
            run=get_doc("Payroll Run",self.payroll_run,ignore_permissions=True)
            if run.docstatus==1 and not getattr(self.flags,"trusted_source",False): throw("Salary Slip inputs cannot be changed after payroll posting.")
        if isinstance(self.variable_inputs,str):
            try: self.variable_inputs=json.loads(self.variable_inputs or "{}")
            except Exception: throw("Variable Payroll Inputs must be valid JSON.")
        if self.variable_inputs is None: self.variable_inputs={}
        if not isinstance(self.variable_inputs,dict): throw("Variable Payroll Inputs must be an object keyed by fieldname.")
    def before_submit(self):
        if not getattr(self.flags,"trusted_source",False):
            throw("Salary Slips can only be submitted by the approved Payroll Run process.")
    def before_cancel(self):
        if not getattr(self.flags,"cancelled_with_run",False): throw(f"Salary Slips are cancelled together with their Payroll Run ({self.payroll_run}). Cancel the run instead.")
    def before_delete(self):
        if self.docstatus==1:
            throw("Posted Salary Slips are retained for payroll audit and cannot be deleted.")


class EmployeeLoanType(Document):
    def validate(self):
        _approval(self)
        self.loan_type_code=(self.loan_type_code or "").strip().upper()
        if not self.loan_type_code or not self.loan_type_name: throw("Loan Type Code and Name are required.")
        if D(self.minimum_amount)<0 or D(self.maximum_amount)<=0 or D(self.minimum_amount)>D(self.maximum_amount): throw("Loan type amount limits are invalid.")
        if int(self.maximum_term_months or 0)<=0 or int(self.maximum_concurrent_loans or 0)<=0: throw("Loan term and concurrent-loan limits must be positive.")
        if D(self.annual_interest_rate)<0: throw("Interest rate cannot be negative.")
        if D(getattr(self,"maximum_deduction_percent_of_net_pay",0) or 0)<0 or D(getattr(self,"maximum_deduction_percent_of_net_pay",0) or 0)>100: throw("Loan type maximum deduction percentage must be between 0 and 100; zero inherits the Finance Settings limit.")
        if int(getattr(self,"deduction_priority",100) or 100)<0: throw("Loan recovery priority cannot be negative.")
        if getattr(self,"allocation_method",None) not in (None,"","Use Finance Default","Oldest Due First","Highest Interest First","Lowest Balance First","Pro Rata"): throw("Select a valid loan recovery allocation method.")
        _account(self.loan_account,["Asset"],party=True)
        if self.default_bank_account: _account(self.default_bank_account,["Asset"])
        if self.interest_income_account: _account(self.interest_income_account,["Income"])
        if D(self.annual_interest_rate)>0 and not self.interest_income_account: throw("An Interest Income Account is required when the loan type charges interest.")
        if not self.effective_from or (self.effective_to and str(self.effective_to)<str(self.effective_from)): throw("Loan Type effective dates are required and must be valid.")
        payroll_recovery=self.recovery_method in ("Payroll Deduction","Either")
        if getattr(self,"_old",None): self._require_recovery_components(payroll_recovery)     # the components reference this loan type, so a new one is created first and completed before use
        if self.deduction_component:
            component=get_doc("Salary Component",self.deduction_component,ignore_permissions=True)
            if component.component_type!="Loan Repayment" or (getattr(component,"account",None) or component.credit_account)!=self.loan_account:
                throw("Loan deduction component must be a Loan Repayment component mapped to this loan receivable account.")
            if payroll_recovery and (component.calculation_type!="Scheduled Loan Deduction" or component.loan_type!=self.name):
                throw("Payroll loan principal component must use Scheduled Loan Deduction and map to this Employee Loan Type.")
        if self.interest_deduction_component:
            interest_component=get_doc("Salary Component",self.interest_deduction_component,ignore_permissions=True)
            if interest_component.component_type!="Loan Interest Recovery" or (getattr(interest_component,"account",None) or interest_component.credit_account)!=self.interest_income_account:
                throw("Loan Interest Recovery component must map to the loan type's Interest Income Account.")
            if payroll_recovery and (interest_component.calculation_type!="Scheduled Loan Interest" or interest_component.loan_type!=self.name):
                throw("Payroll loan interest component must use Scheduled Loan Interest and map to this Employee Loan Type.")
        fingerprint=_fingerprint({"code":self.loan_type_code,"name":self.loan_type_name,"min":str(self.minimum_amount),"max":str(self.maximum_amount),"term":self.maximum_term_months,"rate":str(self.annual_interest_rate),"method":self.repayment_method,"concurrent":self.maximum_concurrent_loans,"service":self.minimum_service_months,"loan_account":self.loan_account,"bank":self.default_bank_account or "","interest_account":self.interest_income_account or "","component":self.deduction_component or "","interest_component":self.interest_deduction_component or "","recovery_method":self.recovery_method,"recovery_cap":str(getattr(self,"maximum_deduction_percent_of_net_pay",0) or 0),"deduction_priority":getattr(self,"deduction_priority",100) or 100,"allow_partial":bool(getattr(self,"allow_partial_recovery",1)),"from":str(self.effective_from),"to":str(self.effective_to or "")})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved Employee Loan Types are immutable; reset approval before changing policy.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def _require_recovery_components(self,payroll_recovery):
        if payroll_recovery and self.approval_status=="Approved" and not self.deduction_component:
            throw("A Loan Repayment Salary Component is required for payroll deduction loan types.")
        if payroll_recovery and D(self.annual_interest_rate)>0 and self.approval_status=="Approved" and not self.interest_deduction_component:
            throw("An interest-bearing payroll loan type requires a Loan Interest Recovery component.")
    def before_submit(self):
        _approved(self)
        self._require_recovery_components(self.recovery_method in ("Payroll Deduction","Either"))

class EmployeeLoanApplication(Document):
    def validate(self):
        _approval(self)
        if not all((self.employee,self.loan_type,self.application_date,self.first_repayment_date,self.currency)): throw("Employee, loan type, application date, first repayment date and currency are required.")
        policy=get_doc("Employee Loan Type",self.loan_type,ignore_permissions=True)
        if policy.docstatus!=1 or policy.approval_status!="Approved": throw("Employee Loan Type must be independently approved and submitted before applications can use it.")
        if not policy.enabled or str(policy.effective_from)>str(self.application_date) or (policy.effective_to and str(policy.effective_to)<str(self.application_date)): throw("This employee loan type is disabled or not effective on the application date.")
        amount=D(self.approved_amount or self.requested_amount); term=int(self.approved_term_months or self.requested_term_months or 0)
        if amount<D(policy.minimum_amount) or amount>D(policy.maximum_amount): throw("Requested/approved amount is outside the loan type policy limits.")
        if term<=0 or term>int(policy.maximum_term_months): throw("Requested/approved term exceeds the loan type policy limit.")
        if str(self.first_repayment_date)<=str(self.application_date): throw("First repayment date must be after the application date.")
        from velora import get_list
        if int(policy.minimum_service_months or 0)>0:
            employee=get_doc("Employee",self.employee,ignore_permissions=True)
            if not getattr(employee,"date_of_joining",None): throw("Employee Date of Joining is required to assess this loan type's minimum service policy.")
            joined=date.fromisoformat(str(employee.date_of_joining)[:10]); applied=date.fromisoformat(str(self.application_date)[:10])
            service_months=max(0,(applied.year-joined.year)*12+applied.month-joined.month-(applied.day<joined.day))
            if service_months<int(policy.minimum_service_months): throw(f"Employee has {service_months} months of service; this loan type requires {policy.minimum_service_months} months.")
        active=get_list("Employee Loan",filters=[["employee","=",self.employee],["loan_type","=",self.loan_type],["docstatus","=",1]],fields=["name","status"],limit=200,ignore_permissions=True)
        active=[x for x in active if x.get("status") not in ("Settled","Written Off")]
        if len(active)>=int(policy.maximum_concurrent_loans): throw("Employee has reached the concurrent loan limit for this loan type.")
        fingerprint=_fingerprint({"employee":self.employee,"loan_type":self.loan_type,"date":str(self.application_date),"requested":str(self.requested_amount),"approved":str(self.approved_amount or ""),"term":term,"first":str(self.first_repayment_date),"purpose":self.purpose or ""})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and old.get("approval_status")==self.approval_status and old.get("approval_hash")!=fingerprint: throw("Approved loan applications are immutable; reset approval before changing terms.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self):
        _approved(self)
        if not self.approval_hash: throw("Independent approval is required for the loan application.")
    def on_submit(self):
        policy=get_doc("Employee Loan Type",self.loan_type,ignore_permissions=True)
        loan=new_doc("Employee Loan",employee=self.employee,loan_type=self.loan_type,loan_application=self.name,loan_date=self.application_date,first_repayment_date=self.first_repayment_date,principal_amount=self.approved_amount or self.requested_amount,annual_interest_rate=policy.annual_interest_rate,term_months=self.approved_term_months or self.requested_term_months,repayment_method=policy.repayment_method,loan_account=policy.loan_account,interest_income_account=policy.interest_income_account,bank_account=self.bank_account or policy.default_bank_account,currency=self.currency,approval_status="Pending",status="Draft")
        loan.insert(ignore_permissions=True)
        db_update(self,generated_loan=loan.name,status="Loan Generated")

class PayrollTaxJurisdiction(Document):
    def validate(self):
        import calendar
        self.jurisdiction_code=(self.jurisdiction_code or "").strip().upper()
        self.country_code=(self.country_code or "").strip().upper()
        if not self.jurisdiction_code or len(self.country_code)!=2 or not self.country_code.isalpha():
            throw("Jurisdiction Code and two-character ISO Country Code are required.")
        try:
            month=int(self.tax_year_start_month or 0); day=int(self.tax_year_start_day or 0)
        except (TypeError, ValueError):
            throw("Tax year start month/day must be whole numbers.")
        if not 1<=month<=12 or not 1<=day<=calendar.monthrange(2000,month)[1]:
            throw("Tax year start month/day is invalid for the selected month.")

class EmployeeTaxProfile(Document):
    def validate(self):
        _approval(self)
        if not all((self.employee,self.jurisdiction,self.tax_rule,self.effective_from)): throw("Employee, Jurisdiction, Tax Rule and Effective From are required.")
        rule=get_doc("Payroll Tax Rule",self.tax_rule,ignore_permissions=True)
        if rule.jurisdiction!=self.jurisdiction: throw("Employee Tax Profile jurisdiction must match its Payroll Tax Rule.")
        if self.effective_to and str(self.effective_to)<str(self.effective_from): throw("Employee Tax Profile effective dates are invalid.")
        existing=get_list("Employee Tax Profile",filters=[["employee","=",self.employee],["jurisdiction","=",self.jurisdiction],["docstatus","!=",2]],fields=["name","effective_from","effective_to"],limit=10000,ignore_permissions=True)
        for profile in existing:
            if profile["name"]==self.name: continue
            existing_end=str(profile.get("effective_to") or "9999-12-31")
            new_end=str(self.effective_to or "9999-12-31")
            if str(self.effective_from)<=existing_end and new_end>=str(profile["effective_from"]):
                throw(f"Employee Tax Profile dates overlap existing profile {profile['name']} for this jurisdiction.")
        fingerprint=_fingerprint({"employee":self.employee,"jurisdiction":self.jurisdiction,"rule":self.tax_rule,"from":str(self.effective_from),"to":str(self.effective_to or ""),"relief":str(self.annual_relief or 0),"exempt":bool(self.tax_exempt)})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved Employee Tax Profiles are immutable; reset approval before changing them.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self):
        _approved(self)

class PayrollTaxBand(Document):
    def validate(self):
        lower=D(self.lower_limit or 0); upper=D(self.upper_limit) if self.upper_limit not in (None,"") else None; rate=D(self.rate)
        if lower<0 or (upper is not None and upper<=lower) or rate<0 or rate>100: throw("Payroll Tax Band limits or rate are invalid.")

class PayrollTaxRule(Document):
    def validate(self):
        _approval(self)
        if not self.rule_code or not self.jurisdiction or not self.effective_from or not self.bands: throw("Tax Rule Code, Jurisdiction, Effective From and tax bands are required.")
        from velora_erp.finance.tax_engine import validate_tax_bands, PayrollTaxError
        try:
            ordered=sorted(self.bands,key=lambda x:int(x.band_sequence))
            sequences=[int(band.band_sequence) for band in ordered]
        except (TypeError, ValueError):
            throw("Every Payroll Tax Rule band requires a whole-number sequence.")
        if len(sequences)!=len(set(sequences)):
            throw("Payroll Tax Rule band sequence values must be unique.")
        try:
            validate_tax_bands([{"lower_limit":band.lower_limit,"upper_limit":band.upper_limit,"rate":band.rate} for band in ordered])
        except PayrollTaxError as exc:
            throw(str(exc))
        try:
            precision=int(self.rounding_precision or 2)
        except (TypeError, ValueError):
            throw("Payroll Tax Rule rounding precision must be a whole number.")
        if not 0<=precision<=8:
            throw("Payroll Tax Rule rounding precision must be between 0 and 8.")
        if self.effective_to and str(self.effective_to)<str(self.effective_from): throw("Tax rule effective dates are invalid.")
        existing_rules=get_list("Payroll Tax Rule",filters=[["jurisdiction","=",self.jurisdiction],["rule_code","=",self.rule_code],["docstatus","!=",2]],fields=["name","effective_from","effective_to"],limit=10000,ignore_permissions=True)
        for existing_rule in existing_rules:
            if existing_rule["name"]==self.name: continue
            existing_end=str(existing_rule.get("effective_to") or "9999-12-31")
            new_end=str(self.effective_to or "9999-12-31")
            if str(self.effective_from)<=existing_end and new_end>=str(existing_rule["effective_from"]):
                throw(f"Payroll Tax Rule effective dates overlap existing rule {existing_rule['name']}.")
        fingerprint=_fingerprint({"code":self.rule_code,"jurisdiction":self.jurisdiction,"from":str(self.effective_from),"to":str(self.effective_to or ""),"basis":self.calculation_basis,"relief":str(self.annual_relief or 0),"bands":[{"seq":x.band_sequence,"lower":str(x.lower_limit),"upper":str(x.upper_limit or ""),"rate":str(x.rate)} for x in self.bands]})
        old=getattr(self,"_old",None) or {}
        if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved" and old.get("approval_hash")!=fingerprint: throw("Approved Payroll Tax Rules are immutable; reset approval before changing rates or bands.")
        self.approval_hash=fingerprint if self.approval_status=="Approved" else None
    def before_submit(self):
        _approved(self)
        if self.approval_status!="Approved": throw("Payroll Tax Rule must be independently approved before submission.")
