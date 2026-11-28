"""Executive read models; caller must supply already permission-filtered records."""
from decimal import Decimal

def executive_dashboard(projects):
    rows=list(projects or []); status={}; budget=Decimal("0"); actual=Decimal("0"); committed=Decimal("0"); overdue=0; risks=0
    for p in rows:
        s=p.get("status","Unknown"); status[s]=status.get(s,0)+1
        budget+=Decimal(str(p.get("approved_budget",0))); actual+=Decimal(str(p.get("actual_cost",0))); committed+=Decimal(str(p.get("open_commitments",0)))
        overdue+=int(p.get("overdue_milestones",0)); risks+=int(p.get("critical_risks",0))
    return {"project_count":len(rows),"status_counts":status,"approved_budget":budget,"actual_cost":actual,"open_commitments":committed,"budget_exposure":actual+committed,"available_budget":budget-actual-committed,"overdue_milestones":overdue,"critical_risks":risks}
