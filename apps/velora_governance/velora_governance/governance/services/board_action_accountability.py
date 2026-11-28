"""Board and committee action accountability metrics."""
from collections import Counter

def build_board_action_accountability(actions, *, today=None):
    rows=list(actions or [])
    terminal={"Completed","Closed","Cancelled","Resolved"}
    open_rows=[r for r in rows if r.get("status") not in terminal]
    overdue=[r for r in open_rows if r.get("overdue") or r.get("status")=="Overdue"]
    unassigned=[r for r in open_rows if not r.get("owner") or not str(r.get("owner")).strip()]
    due_soon=[r for r in open_rows if r.get("days_until_due") is not None and 0<=int(r["days_until_due"])<=30]
    by_owner=Counter(str(r.get("owner") or "Unassigned") for r in open_rows)
    by_committee=Counter(str(r.get("committee") or "Unassigned") for r in open_rows)
    return {"total":len(rows),"open":len(open_rows),"completed":sum(r.get("status")=="Completed" for r in rows),
      "overdue":len(overdue),"due_within_30_days":len(due_soon),"unassigned":len(unassigned),
      "completion_rate_percent":round(100*sum(r.get("status")=="Completed" for r in rows)/len(rows),2) if rows else 0,
      "open_by_owner":dict(sorted(by_owner.items())),"open_by_committee":dict(sorted(by_committee.items())),
      "attention_items":[{"id":r.get("id"),"title":r.get("title"),"owner":r.get("owner"),"committee":r.get("committee"),
       "due_date":r.get("due_date"),"days_until_due":r.get("days_until_due"),"reason":"Overdue" if r in overdue else "Unassigned" if r in unassigned else "Due soon"}
       for r in overdue+unassigned+due_soon] }
