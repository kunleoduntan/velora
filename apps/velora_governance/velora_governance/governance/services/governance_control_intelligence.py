"""Risk-control integration and control effectiveness intelligence."""
from collections import Counter

def build_control_intelligence(controls, risks=None, tests=None):
    controls=list(controls or []); risks=list(risks or []); tests=list(tests or [])
    risk_ids={r.get("id") or r.get("name") for r in risks}
    test_by_control={}
    for t in tests: test_by_control.setdefault(t.get("control_id"),[]).append(t)
    results=[]
    for c in controls:
        cid=c.get("id") or c.get("name")
        linked=[r for r in risks if (r.get("control_id")==cid or cid in (r.get("control_ids") or []))]
        ct=test_by_control.get(cid,[])
        failed=[t for t in ct if str(t.get("result","")).lower() in {"fail","failed","ineffective","exception"}]
        overdue=[t for t in ct if t.get("overdue") or t.get("status")=="Overdue"]
        status="Needs Testing" if not ct else "Ineffective" if failed else "Overdue Testing" if overdue else "Effective"
        results.append({"control_id":cid,"title":c.get("title"),"owner":c.get("owner"),"risk_count":len(linked),
          "risk_ids":[r.get("id") or r.get("name") for r in linked],"test_count":len(ct),"failed_tests":len(failed),
          "overdue_tests":len(overdue),"status":status,"priority":"High" if failed or overdue or not ct else "Normal"})
    counts=Counter(x["status"] for x in results)
    return {"controls_total":len(controls),"controls_tested":sum(bool(test_by_control.get(c.get("id") or c.get("name"))) for c in controls),
      "controls_ineffective":counts["Ineffective"],"controls_overdue_testing":counts["Overdue Testing"],
      "controls_needing_testing":counts["Needs Testing"],"risk_control_coverage":round(100*sum(bool(x["risk_count"]) for x in results)/len(controls),2) if controls else 0,
      "controls":results,"attention_controls":[x for x in results if x["priority"]=="High"]}
