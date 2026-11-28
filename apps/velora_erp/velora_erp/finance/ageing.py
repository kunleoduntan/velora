"""Receivables/payables ageing and collection/payment prioritisation."""
from __future__ import annotations
from datetime import date
from decimal import Decimal, InvalidOperation

class AgeingError(ValueError): pass

def _d(value, field):
    try: out=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError) as exc: raise AgeingError(f"{field} must be numeric") from exc
    if not out.is_finite() or out<0: raise AgeingError(f"{field} must be finite and non-negative")
    return out

def _date(value, field):
    try: return date.fromisoformat(str(value))
    except (TypeError,ValueError) as exc: raise AgeingError(f"{field} must be an ISO date") from exc

def ageing_bucket(days_overdue):
    if days_overdue<=0: return "Not Due"
    if days_overdue<=30: return "1-30 Days"
    if days_overdue<=60: return "31-60 Days"
    if days_overdue<=90: return "61-90 Days"
    return "Over 90 Days"

def build_ageing_report(*, open_items, as_of_date, party_type):
    """Age open invoices supplied by the settlement read model, grouped by currency."""
    as_of=_date(as_of_date,"as_of_date")
    if party_type not in ("Customer","Supplier"): raise AgeingError("Party Type must be Customer or Supplier")
    buckets=("Not Due","1-30 Days","31-60 Days","61-90 Days","Over 90 Days")
    by_currency={}; rows=[]
    for item in open_items:
        if item.get("party_type",party_type)!=party_type: raise AgeingError("Ageing input contains the wrong party type")
        amount=_d(item.get("outstanding_amount"),"outstanding_amount")
        if amount==0: continue
        due=_date(item.get("due_date"),"due_date")
        days=(as_of-due).days
        bucket=ageing_bucket(days)
        currency=str(item.get("currency") or "").upper()
        if len(currency)!=3: raise AgeingError("Each open item requires a three-letter currency")
        summary=by_currency.setdefault(currency,{b:Decimal("0") for b in buckets})
        summary[bucket]+=amount
        rows.append({"party":item.get("party"),"invoice":item.get("invoice"),"due_date":due.isoformat(),"days_overdue":max(days,0),"bucket":bucket,"currency":currency,"outstanding_amount":amount,"disputed":bool(item.get("disputed",False))})
    rows.sort(key=lambda x:(x["currency"],x["party"] or "",-x["days_overdue"],x["invoice"] or ""))
    totals={currency:{**values,"total":sum(values.values(),Decimal("0"))} for currency,values in sorted(by_currency.items())}
    return {"party_type":party_type,"as_of_date":as_of.isoformat(),"rows":rows,"totals_by_currency":totals,"cross_currency_total":None,"source":"open invoice balances net of approved allocations","ledger_posted":False}

def build_dunning_candidates(*, ageing_report, minimum_days_overdue=1, minimum_amount_by_currency=None, exclude_disputed=True):
    if not isinstance(ageing_report,dict) or ageing_report.get("source")!="open invoice balances net of approved allocations": raise AgeingError("A validated ageing report is required")
    if not isinstance(minimum_days_overdue,int) or minimum_days_overdue<1: raise AgeingError("minimum_days_overdue must be a positive integer")
    minimum_amount_by_currency=minimum_amount_by_currency or {}
    candidates=[]
    for row in ageing_report.get("rows",[]):
        if row["days_overdue"]<minimum_days_overdue or (exclude_disputed and row["disputed"]): continue
        threshold=_d(minimum_amount_by_currency.get(row["currency"],0),"minimum amount threshold")
        if row["outstanding_amount"]<threshold: continue
        candidates.append({**row,"recommended_action":"Review for collection/payment follow-up","message_sent":False,"automatic_contact":False})
    return {"party_type":ageing_report["party_type"],"as_of_date":ageing_report["as_of_date"],"candidates":candidates,"messages_sent":0,"requires_human_review":True}
