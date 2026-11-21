"""Finance-owned payroll calculation and accounting preparation services.

Salary formulas are parsed as a restricted arithmetic AST. No Python eval, imports,
attribute access, function calls, file access or arbitrary code execution is allowed.
"""
from __future__ import annotations
import ast
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from .tax_engine import calculate_period_tax, calculate_ytd_tax_adjustment, calculate_ytd_tax_adjustment

CENT = Decimal("0.01")
ZERO = Decimal("0")

class PayrollCalculationError(ValueError): pass

def money(value):
    try: amount=Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError) as exc: raise PayrollCalculationError("Payroll amount must be numeric") from exc
    if not amount.is_finite(): raise PayrollCalculationError("Payroll amount must be finite")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)

def _eval(node, context):
    if isinstance(node, ast.Expression): return _eval(node.body, context)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int,float)): return Decimal(str(node.value))
    if isinstance(node, ast.Name):
        if node.id not in context: raise PayrollCalculationError(f"Formula references unknown payroll value {node.id!r}")
        return Decimal(str(context[node.id]))
    if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Mod,ast.Pow):
        left,right=_eval(node.left,context),_eval(node.right,context)
        if isinstance(node.op,ast.Add): return left+right
        if isinstance(node.op,ast.Sub): return left-right
        if isinstance(node.op,ast.Mult): return left*right
        if isinstance(node.op,ast.Div):
            if right==0: raise PayrollCalculationError("Payroll formula division by zero")
            return left/right
        if isinstance(node.op,ast.Mod):
            if right==0: raise PayrollCalculationError("Payroll formula modulo by zero")
            return left%right
        if right != right.to_integral_value() or abs(right)>12: raise PayrollCalculationError("Formula exponent must be an integer between -12 and 12")
        return left**int(right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.UAdd,ast.USub):
        value=_eval(node.operand,context); return value if isinstance(node.op,ast.UAdd) else -value
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {"MIN","MAX","ABS","ROUND","IF"} and not node.keywords:
        if node.func.id=="IF":
            if len(node.args)!=3: raise PayrollCalculationError("IF requires condition, true value and false value")
            condition=ast.unparse(node.args[0])
            return _eval(node.args[1] if evaluate_condition(condition,context) else node.args[2],context)
        vals=[_eval(x,context) for x in node.args]
        if not vals: raise PayrollCalculationError(f"{node.func.id} requires at least one argument")
        if node.func.id=="MIN": return min(vals)
        if node.func.id=="MAX": return max(vals)
        if node.func.id=="ABS":
            if len(vals)!=1: raise PayrollCalculationError("ABS requires one argument")
            return abs(vals[0])
        if len(vals) not in (1,2): raise PayrollCalculationError("ROUND requires one or two arguments")
        places=int(vals[1]) if len(vals)==2 else 2
        if places < 0 or places > 6: raise PayrollCalculationError("ROUND precision must be between 0 and 6")
        return vals[0].quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP)
    raise PayrollCalculationError("Formula contains an unsupported operation")


STANDARD_NAMES = frozenset({"base_salary","gross","net","taxable_gross","pensionable_gross","days_worked","days_in_period","overtime_hours",
                            "employee_type","department","designation","branch","grade","service_months"})
_FORMULA_FUNCS = {"MIN","MAX","ABS","ROUND","IF"}

def check_expression(text, kind="formula"):
    """Validate a formula or condition WITHOUT running it. Returns the set of variable names it uses.
    Raises PayrollCalculationError for syntax errors and for anything the engine would refuse at payroll time."""
    if kind not in ("formula","condition"): raise ValueError(kind)
    if text in (None,""):
        if kind=="formula": raise PayrollCalculationError("A formula is required")
        return set()
    expression=str(text)
    if kind=="condition":
        expression=re.sub(r"\bAND\b","and",expression,flags=re.I); expression=re.sub(r"\bOR\b","or",expression,flags=re.I); expression=re.sub(r"\bNOT\b","not",expression,flags=re.I)
    try: tree=ast.parse(expression,mode="eval")
    except SyntaxError as exc: raise PayrollCalculationError(f"Payroll {kind} has invalid syntax: {exc.msg}") from exc
    names=set()
    def walk(n, allow_bool):
        if isinstance(n,ast.Expression): return walk(n.body,allow_bool)
        if isinstance(n,ast.Constant):
            if isinstance(n.value,(int,float)) and not isinstance(n.value,bool): return
            if allow_bool and isinstance(n.value,(bool,str)): return
            raise PayrollCalculationError(f"Payroll {kind} contains an unsupported value {n.value!r}")
        if isinstance(n,ast.Name): names.add(n.id); return
        if isinstance(n,ast.BinOp) and type(n.op) in (ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Mod,ast.Pow):
            walk(n.left,False); walk(n.right,False); return
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub)): walk(n.operand,False); return
        if allow_bool and isinstance(n,ast.UnaryOp) and isinstance(n.op,ast.Not): walk(n.operand,True); return
        if allow_bool and isinstance(n,ast.BoolOp):
            for v in n.values: walk(v,True)
            return
        if allow_bool and isinstance(n,ast.Compare):
            if any(type(o) not in (ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE) for o in n.ops): raise PayrollCalculationError("Unsupported comparison; use ==, !=, <, <=, > or >=")
            walk(n.left,True)
            for c in n.comparators: walk(c,True)
            return
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in _FORMULA_FUNCS and not n.keywords:
            if n.func.id=="IF":
                if len(n.args)!=3: raise PayrollCalculationError("IF requires a condition, a value if true and a value if false")
                walk(n.args[0],True); walk(n.args[1],False); walk(n.args[2],False); return
            if not n.args: raise PayrollCalculationError(f"{n.func.id} requires at least one argument")
            if n.func.id=="ABS" and len(n.args)!=1: raise PayrollCalculationError("ABS requires one argument")
            if n.func.id=="ROUND" and len(n.args) not in (1,2): raise PayrollCalculationError("ROUND requires one or two arguments")
            for a in n.args: walk(a,False)
            return
        raise PayrollCalculationError(f"Payroll {kind} contains an unsupported operation ({type(n).__name__}); allowed: + - * / % **, MIN, MAX, ABS, ROUND, IF and comparisons")
    walk(tree, kind=="condition")
    return names

def check_expression_names(names, known, label):
    unknown=sorted(n for n in names if n not in known)
    if unknown: raise PayrollCalculationError(f"{label} refers to unknown value(s): {', '.join(unknown)}. Available: standard payroll values, components earlier in the sequence, and inputs.")

def evaluate_formula(formula, context):
    if not isinstance(formula,str) or not formula.strip(): raise PayrollCalculationError("A formula is required")
    try: tree=ast.parse(formula,mode="eval")
    except SyntaxError as exc: raise PayrollCalculationError("Payroll formula has invalid syntax") from exc
    return _eval(tree, context)

def evaluate_condition(condition, context):
    if condition in (None, ""): return True
    # Accept payroll-friendly uppercase boolean keywords while retaining strict AST validation.
    expression=re.sub(r"\bAND\b","and",str(condition),flags=re.I)
    expression=re.sub(r"\bOR\b","or",expression,flags=re.I)
    expression=re.sub(r"\bNOT\b","not",expression,flags=re.I)
    try: tree=ast.parse(expression,mode="eval")
    except SyntaxError as exc: raise PayrollCalculationError("Payroll condition has invalid syntax") from exc
    def ev(n):
        if isinstance(n,ast.Expression): return ev(n.body)
        if isinstance(n,ast.Constant) and isinstance(n.value,(int,float,bool,str)): return n.value
        if isinstance(n,ast.Name):
            if n.id not in context: raise PayrollCalculationError(f"Condition references unknown payroll value {n.id!r}")
            return context[n.id]
        if isinstance(n,ast.BoolOp) and isinstance(n.op,(ast.And,ast.Or)):
            values=[bool(ev(x)) for x in n.values]; return all(values) if isinstance(n.op,ast.And) else any(values)
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,ast.Not): return not bool(ev(n.operand))
        if isinstance(n,ast.Compare):
            left=ev(n.left)
            for op,right_node in zip(n.ops,n.comparators):
                right=ev(right_node)
                if type(op) not in (ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE): raise PayrollCalculationError("Unsupported condition comparison")
                ok={ast.Eq:left==right,ast.NotEq:left!=right,ast.Lt:left<right,ast.LtE:left<=right,ast.Gt:left>right,ast.GtE:left>=right}[type(op)]
                if not ok:return False
                left=right
            return True
        raise PayrollCalculationError("Condition contains an unsupported operation")
    try: return bool(ev(tree))
    except TypeError as exc: raise PayrollCalculationError("Payroll condition compares incompatible values (text with a number)") from exc

def calculate_payroll(*, base_salary, components, inputs=None, employee_context=None, days_worked=None, days_in_period=None, overtime_hours=0):
    base=money(base_salary)
    if base<0: raise PayrollCalculationError("Base salary cannot be negative")
    inputs=inputs or {}
    if not isinstance(inputs,dict): raise PayrollCalculationError("Payroll inputs must be an object keyed by salary component code")
    if (days_worked is None) != (days_in_period is None): raise PayrollCalculationError("Days Worked and Days in Period must be supplied together")
    if days_in_period is not None and (Decimal(str(days_in_period))<=0 or Decimal(str(days_worked))<0 or Decimal(str(days_worked))>Decimal(str(days_in_period))):
        raise PayrollCalculationError("Worked days must be between zero and the positive period days")
    context={"base_salary":base,"gross":ZERO,"net":ZERO,"days_worked":Decimal(str(days_worked or 0)),"days_in_period":Decimal(str(days_in_period or 0)),"overtime_hours":Decimal(str(overtime_hours or 0))}
    for key,value in (employee_context or {}).items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",str(key)): raise PayrollCalculationError("Employee payroll context keys must be valid variable names")
        context[str(key)]=value
    for key,value in inputs.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",str(key)): raise PayrollCalculationError("Payroll input keys must be valid variable names")
        if isinstance(value,bool): value=1 if value else 0
        context[str(key)]=Decimal(str(value or 0))
    lines=[]; tax_details=[]; categories={"Earning":ZERO,"Deduction":ZERO,"Employer Contribution":ZERO,"Loan Repayment":ZERO,"Loan Interest Recovery":ZERO,"Advance Recovery":ZERO}
    context["taxable_gross"]=ZERO; context["pensionable_gross"]=ZERO
    seen=set(); tax_done=False
    for component in sorted(components,key=lambda x:(int(x.get("sequence") or 100),str(x.get("component_code") or ""))):
        code=str(component.get("component_code") or "").strip()
        if not code or code in seen: raise PayrollCalculationError("Salary component codes must be non-empty and unique in a structure")
        if code in STANDARD_NAMES:
            raise PayrollCalculationError(f"Salary component code {code!r} is reserved: it would overwrite a payroll value such as gross or net. Use a different code.")
        seen.add(code); kind=component.get("component_type")
        if not evaluate_condition(component.get("condition"),context):
            context[code]=ZERO
            continue
        if kind not in categories: raise PayrollCalculationError(f"Salary component {code}: invalid component type")
        calc=component.get("calculation_type")
        if calc=="Fixed": amount=money(component.get("amount"))
        elif calc=="Percentage of Base": amount=money(base*Decimal(str(component.get("rate") or 0))/Decimal("100"))
        elif calc=="Percentage of Gross": amount=money(context["gross"]*Decimal(str(component.get("rate") or 0))/Decimal("100"))
        elif calc=="Percentage of Pensionable Gross": amount=money(context["pensionable_gross"]*Decimal(str(component.get("rate") or 0))/Decimal("100"))
        elif calc=="Formula": amount=money(evaluate_formula(component.get("formula"),context))
        elif calc in ("Scheduled Loan Deduction","Scheduled Loan Interest"):
            amount=money(component.get("scheduled_amount",0))
        elif calc=="Progressive Tax":
            bands=component.get("tax_bands") or []
            basis=component.get("tax_calculation_basis","Annualised Period Income")
            periods=int(component.get("periods_per_year") or 12)
            if basis=="Cumulative YTD":
                prior_periods=int(component.get("prior_periods_elapsed") or 0)
                elapsed=prior_periods+1
                if elapsed>periods:
                    raise PayrollCalculationError("Cumulative PAYE has more processed periods than the configured periods per year")
                tax=calculate_ytd_tax_adjustment(
                    ytd_taxable_income=Decimal(str(component.get("prior_ytd_taxable_income") or 0))+context.get("taxable_gross",ZERO),
                    prior_tax_withheld=component.get("prior_tax_withheld",0),
                    remaining_periods=periods-elapsed, periods_per_year=periods, bands=bands,
                    annual_relief=component.get("annual_relief",0), precision=int(component.get("rounding_precision") or 2),
                )
                adjustment=Decimal(str(tax["current_period_adjustment"]))
                refund_credit=max(ZERO,-adjustment)
                amount=money(max(ZERO,adjustment))
                component_tax={"component_code":code,**{k:str(v) for k,v in tax.items()},
                    "tax_rule":component.get("tax_rule"),"tax_year_start":component.get("tax_year_start"),
                    "tax_liability_account":component.get("tax_liability_account"),
                    "refund_credit_amount":str(money(refund_credit)),
                    "actual_withheld":str(amount),
                    "requires_refund_or_credit_review":bool(refund_credit)}
            else:
                tax=calculate_period_tax(period_taxable_income=context.get("taxable_gross",ZERO),periods_per_year=periods,bands=bands,annual_relief=component.get("annual_relief",0),precision=int(component.get("rounding_precision") or 2),calculation_basis=basis)
                amount=money(tax["period_tax"])
                component_tax={"component_code":code,**{k:str(v) for k,v in tax.items()},"tax_rule":component.get("tax_rule"),"actual_withheld":str(amount)}
            tax_details.append(component_tax); tax_done=True
        elif calc=="Input": amount=money(inputs.get(component.get("input_fieldname") or code,inputs.get(code,component.get("input_default") or 0)))
        else: raise PayrollCalculationError(f"Salary component {code}: unsupported calculation type")
        if amount<0: raise PayrollCalculationError(f"Salary component {code}: calculated amount cannot be negative")
        if component.get("prorate_by_attendance"):
            if days_in_period is None: raise PayrollCalculationError(f"Salary component {code}: attendance proration requires worked and period days")
            amount=money(amount*Decimal(str(days_worked))/Decimal(str(days_in_period)))
        categories[kind]+=amount
        if kind=="Deduction" and component.get("reduces_taxable_income"):
            if tax_done: raise PayrollCalculationError(f"Salary component {code} reduces taxable income but is sequenced after the tax component; give it an earlier sequence.")
            context["taxable_gross"]=max(ZERO,context["taxable_gross"]-amount)
        if kind=="Earning":
            context["gross"]+=amount
            if component.get("taxable"): context["taxable_gross"]+=amount
            if component.get("pensionable"): context["pensionable_gross"]+=amount
        context["net"]=money(context["gross"]-categories["Deduction"]-categories["Loan Repayment"]-categories["Loan Interest Recovery"]-categories["Advance Recovery"])
        context[code]=amount
        lines.append({"component_code":code,"component_name":component.get("component_name") or code,"component_type":kind,"amount":amount,"debit_account":component.get("debit_account"),"credit_account":component.get("credit_account"),"statutory_scheme":component.get("statutory_scheme"),"taxable":bool(component.get("taxable")),"pensionable":bool(component.get("pensionable")),"hide_on_payslip":bool(component.get("hide_on_payslip")),"cost_centre":component.get("cost_centre") or None,"business_unit":component.get("business_unit") or None})
    gross=money(categories["Earning"])
    deductions=money(categories["Deduction"]+categories["Loan Repayment"]+categories["Loan Interest Recovery"]+categories["Advance Recovery"])
    if deductions>gross: raise PayrollCalculationError("Total employee deductions, loan repayments and advance recoveries exceed gross earnings")
    net=money(gross-deductions); employer=money(categories["Employer Contribution"])
    context["net"]=net
    return {"lines":lines,"gross_earnings":gross,"employee_deductions":money(categories["Deduction"]),"loan_repayments":money(categories["Loan Repayment"]),"loan_interest_repayments":money(categories["Loan Interest Recovery"]),"advance_recoveries":money(categories["Advance Recovery"]),"total_deductions":deductions,"employer_contributions":employer,"net_pay":net,"total_employer_cost":money(gross+employer),"tax_computation":tax_details}

def payroll_posting_lines(*, employee, result, payroll_payable_account, cost_centre=None, business_unit=None):
    """Build balanced base-currency posting instructions; caller submits via central engine."""
    lines=[]
    for item in result["lines"]:
        amount=money(item["amount"])
        if not amount: continue
        common={"party_type":"Employee" if item["component_type"] in ("Loan Repayment","Advance Recovery") else None,
                "party":employee if item["component_type"] in ("Loan Repayment","Advance Recovery") else None,
                "cost_centre":item.get("cost_centre") or cost_centre,
                "business_unit":item.get("business_unit") or business_unit,
                "line_description":f"Payroll {item['component_name']} — {employee}"}
        if item["component_type"] in ("Earning","Employer Contribution"):
            if not item.get("debit_account"): raise PayrollCalculationError(f"{item['component_code']}: an expense debit account is required")
            lines.append({"account":item["debit_account"],"debit":amount,"credit":0,**common})
            if item["component_type"]=="Employer Contribution":
                if not item.get("credit_account"): raise PayrollCalculationError(f"{item['component_code']}: an employer contribution liability account is required")
                lines.append({"account":item["credit_account"],"debit":0,"credit":amount,**common})
        else:
            if not item.get("credit_account"): raise PayrollCalculationError(f"{item['component_code']}: a deduction settlement account is required")
            lines.append({"account":item["credit_account"],"debit":0,"credit":amount,**common})
    if result["net_pay"]:
        lines.append({"account":payroll_payable_account,"debit":0,"credit":result["net_pay"],"party_type":"Employee","party":employee,"cost_centre":cost_centre,"business_unit":business_unit,"line_description":f"Net payroll payable — {employee}"})
    return lines


def allocate_loan_recoveries(allocations, *, net_before_loan_recovery, overall_percent=30, minimum_net_pay=0, loan_type_policies=None, allocation_method="Oldest Due First", allow_partial=True):
    """Apply one combined net-pay ceiling to all loan principal and interest recoveries.

    Allocations are grouped by loan type for policy caps, then allocated to individual
    loans. The result preserves loan-level references and never mutates schedules.
    """
    net=money(net_before_loan_recovery); floor=money(minimum_net_pay)
    pct=Decimal(str(overall_percent or 0))
    if net<0 or floor<0 or pct<0 or pct>100:
        raise PayrollCalculationError("Loan recovery protection settings are outside valid ranges")
    policies=loan_type_policies or {}
    floor_capacity=max(ZERO,net-floor)
    percent_capacity=money(net*pct/Decimal("100")) if pct>0 else floor_capacity
    overall_cap=min(floor_capacity,percent_capacity)
    rows=[]
    for source in allocations or []:
        item=dict(source); principal=money(item.get("amount",0)); interest=money(item.get("interest_amount",0))
        if principal<0 or interest<0: raise PayrollCalculationError("Loan recovery allocations cannot be negative")
        item["amount"]=ZERO; item["interest_amount"]=ZERO
        item["_due_principal"]=principal; item["_due_interest"]=interest
        item["_due_total"]=money(principal+interest)
        rows.append(item)
    groups={}
    for item in rows: groups.setdefault(item.get("loan_type") or "",[]).append(item)
    def group_order(pair):
        loan_type, items=pair; policy=policies.get(loan_type,{})
        return (int(policy.get("deduction_priority") or 100),loan_type)
    remaining=overall_cap; total_allowed=ZERO; type_summary={}
    for loan_type, items in sorted(groups.items(),key=group_order):
        policy=policies.get(loan_type,{})
        due=money(sum((x["_due_total"] for x in items),ZERO))
        type_pct=Decimal(str(policy.get("maximum_deduction_percent_of_net_pay") or 0))
        if type_pct<0 or type_pct>100: raise PayrollCalculationError(f"Loan type {loan_type} has an invalid deduction percentage")
        type_cap=money(net*type_pct/Decimal("100")) if type_pct>0 else due
        target=min(due,type_cap,remaining)
        partial=bool(allow_partial and policy.get("allow_partial_recovery",True))
        if not partial and target<due: target=ZERO
        method=policy.get("allocation_method") or allocation_method
        if method=="Highest Interest First": items=sorted(items,key=lambda x:(-Decimal(str(x.get("annual_interest_rate") or 0)),str(x.get("due_date") or "9999"),str(x.get("employee_loan") or "")))
        elif method=="Lowest Balance First": items=sorted(items,key=lambda x:(Decimal(str(x.get("outstanding_principal") or 0)),str(x.get("due_date") or "9999"),str(x.get("employee_loan") or "")))
        elif method=="Pro Rata": items=sorted(items,key=lambda x:(str(x.get("due_date") or "9999"),str(x.get("employee_loan") or "")))
        else: items=sorted(items,key=lambda x:(str(x.get("due_date") or "9999"),str(x.get("employee_loan") or "")))
        if method=="Pro Rata" and due>0 and target>0:
            assigned=ZERO
            for n,item in enumerate(items):
                share=target-assigned if n==len(items)-1 else money(target*item["_due_total"]/due)
                share=min(share,item["_due_total"]); assigned+=share
                # Interest is recovered before principal within each loan's due amount.
                interest=min(item["_due_interest"],share); principal=min(item["_due_principal"],money(share-interest))
                item["interest_amount"]=interest; item["amount"]=principal
        else:
            left=target
            for item in items:
                if left<=0: break
                take=min(left,item["_due_total"]); interest=min(item["_due_interest"],take); principal=min(item["_due_principal"],money(take-interest))
                item["interest_amount"]=interest; item["amount"]=principal; left=money(left-interest-principal)
        actual=money(sum((x["amount"]+x["interest_amount"] for x in items),ZERO))
        remaining=money(remaining-actual); total_allowed+=actual
        type_summary[loan_type]={"scheduled":due,"allowed":actual,"deferred":money(due-actual),"cap":min(type_cap,due)}
    for item in rows:
        item.pop("_due_principal",None); item.pop("_due_interest",None); item.pop("_due_total",None)
    scheduled=money(sum((money(x.get("amount",0))+money(x.get("interest_amount",0)) for x in allocations or []),ZERO))
    return {"allocations":rows,"net_before_loan_recovery":net,"overall_cap":overall_cap,"scheduled_total":scheduled,"allowed_total":money(total_allowed),"deferred_total":money(scheduled-total_allowed),"net_after_loan_recovery":money(net-total_allowed),"type_summary":type_summary}


def reconcile_payroll_settlements(*, salary_slips, posted_payment_lines, tolerance="0.01"):
    """Reconcile Salary Slip net pay and paid/outstanding balances to posted payment lines.

    salary_slips: [{salary_slip, net_pay, paid_amount, outstanding_amount}]
    posted_payment_lines: [{payment, salary_slip, amount}]. Only submitted/posted
    Payroll Payments may be supplied. The helper is read-only and never posts.
    """
    tol=Decimal(str(tolerance))
    if not tol.is_finite() or tol<0:
        raise PayrollCalculationError("Payroll settlement tolerance must be finite and non-negative")
    slips={}
    for slip in salary_slips:
        name=str(slip.get("salary_slip") or "").strip()
        if not name or name in slips:
            raise PayrollCalculationError("Salary Slip references must be nonblank and unique")
        net=money(slip.get("net_pay",0)); paid=money(slip.get("paid_amount",0)); outstanding=money(slip.get("outstanding_amount",0))
        if min(net,paid,outstanding)<0 or paid>net:
            raise PayrollCalculationError(f"{name}: invalid net pay, paid or outstanding amount")
        if money(net-paid)!=outstanding:
            raise PayrollCalculationError(f"{name}: Salary Slip paid and outstanding amounts do not reconcile to net pay")
        slips[name]={"net_pay":net,"paid_amount":paid,"outstanding_amount":outstanding}
    totals={name:ZERO for name in slips}; seen=set()
    for line in posted_payment_lines:
        slip=str(line.get("salary_slip") or "").strip(); payment=str(line.get("payment") or "").strip()
        if slip not in slips: raise PayrollCalculationError(f"Payment line references unknown Salary Slip {slip!r}")
        if not payment: raise PayrollCalculationError("Posted payment lines require a Payroll Payment reference")
        key=(payment,slip)
        if key in seen: raise PayrollCalculationError(f"Duplicate Salary Slip line in Payroll Payment {payment}")
        seen.add(key); amount=money(line.get("amount",0))
        if amount<=0: raise PayrollCalculationError("Posted payroll payment amounts must be positive")
        totals[slip]=money(totals[slip]+amount)
    results=[]; blockers=[]
    for name, slip in slips.items():
        difference=money(totals[name]-slip["paid_amount"])
        remaining=money(slip["net_pay"]-totals[name])
        ok=abs(difference)<=tol and remaining>=-tol
        if not ok: blockers.append(name)
        results.append({"salary_slip":name,"net_pay":slip["net_pay"],"posted_payments":totals[name],"recorded_paid_amount":slip["paid_amount"],"recorded_outstanding":slip["outstanding_amount"],"payment_difference":difference,"payment_implied_outstanding":remaining,"reconciled":ok})
    return {"salary_slip_count":len(results),"reconciled_count":sum(1 for x in results if x["reconciled"]),"exception_count":len(blockers),"publication_blockers":blockers,"results":results,"reconciled":not blockers,"read_only":True,"posting_side_effects":False,"tolerance":tol}


def build_statutory_contribution_register(*, salary_slips, period_start, period_end, currency):
    """Aggregate approved payroll statutory deductions and employer contributions.

    Only submitted Salary Slips are accepted. Each item must contain a stored
    calculation_lines snapshot; no live Salary Component values are re-read.
    """
    if not period_start or not period_end or str(period_start)>str(period_end) or not currency:
        raise PayrollCalculationError("A valid reporting period and currency are required")
    totals={}; source_slips=set(); blockers=[]
    for slip in salary_slips:
        if int(slip.get("docstatus",0) or 0)!=1: raise PayrollCalculationError("Statutory register accepts submitted Salary Slips only")
        name=str(slip.get("salary_slip") or slip.get("name") or "").strip()
        if not name or name in source_slips: raise PayrollCalculationError("Salary Slip references must be nonblank and unique")
        source_slips.add(name)
        if str(slip.get("period_start"))<str(period_start) or str(slip.get("period_end"))>str(period_end):
            raise PayrollCalculationError(f"{name}: Salary Slip period falls outside the requested reporting window")
        if slip.get("currency")!=currency: raise PayrollCalculationError(f"{name}: Salary Slip currency differs from the register currency")
        lines=slip.get("calculation_lines") or []
        if isinstance(lines,str):
            import json
            lines=json.loads(lines)
        for line in lines:
            scheme=str(line.get("statutory_scheme") or "").strip()
            kind=line.get("component_type")
            if not scheme or kind not in ("Deduction","Employer Contribution"): continue
            account=line.get("credit_account")
            if not account:
                blockers.append(f"{name}/{line.get('component_code')}: statutory payable account is missing")
                continue
            key=(scheme,kind,account)
            item=totals.setdefault(key,{"statutory_scheme":scheme,"contribution_type":kind,"payable_account":account,"amount":ZERO,"employee_count":0,"salary_slips":[]})
            amount=money(line.get("amount",0))
            if amount<0: raise PayrollCalculationError("Statutory contribution amounts cannot be negative")
            item["amount"]=money(item["amount"]+amount)
            if name not in item["salary_slips"]:
                item["salary_slips"].append(name); item["employee_count"]+=1
    rows=[]
    for item in totals.values():
        item["salary_slips"]=sorted(item["salary_slips"]); rows.append(item)
    rows.sort(key=lambda x:(x["statutory_scheme"],x["contribution_type"],x["payable_account"]))
    return {"period_start":str(period_start),"period_end":str(period_end),"currency":currency,"rows":rows,"total_amount":money(sum((x["amount"] for x in rows),ZERO)),"source_salary_slip_count":len(source_slips),"publication_blockers":blockers,"complete":not blockers,"read_only":True,"posting_side_effects":False}
