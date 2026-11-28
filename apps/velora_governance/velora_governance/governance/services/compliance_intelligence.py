"""Compliance obligation monitoring and readiness intelligence."""
from collections import Counter

def build_compliance_intelligence(obligations, *, today=None):
    rows=list(obligations or []); terminal={"Completed","Compliant","Closed","Not Applicable"}
    overdue=[r for r in rows if r.get("overdue") or r.get("status")=="Overdue"]
    open_rows=[r for r in rows if r.get("status") not in terminal]
    due_soon=[r for r in open_rows if r.get("days_until_due") is not None and 0<=int(r["days_until_due"])<=30]
    missing_owner=[r for r in open_rows if not r.get("owner")]
    by_authority=Counter(str(r.get("authority") or "Unspecified") for r in rows)
    by_status=Counter(str(r.get("status") or "Unspecified") for r in rows)
    attention=[]
    for r in overdue+due_soon+missing_owner:
        reasons=[]
        if r in overdue: reasons.append("Overdue")
        if r in due_soon: reasons.append("Due within 30 days")
        if r in missing_owner: reasons.append("Owner missing")
        attention.append({"id":r.get("id"),"title":r.get("title"),"authority":r.get("authority"),"owner":r.get("owner"),
          "due_date":r.get("due_date"),"reasons":reasons,"priority":"Critical" if r in overdue else "High"})
    return {"total":len(rows),"open":len(open_rows),"overdue":len(overdue),"due_within_30_days":len(due_soon),
      "missing_owner":len(missing_owner),"compliance_rate_percent":round(100*sum(r.get("status") in terminal for r in rows)/len(rows),2) if rows else 0,
      "by_authority":dict(by_authority),"by_status":dict(by_status),"attention_items":attention}
