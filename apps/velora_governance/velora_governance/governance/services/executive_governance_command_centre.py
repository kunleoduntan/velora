"""Executive governance command-centre aggregation."""
from .governance_intelligence import build_governance_intelligence
from .board_action_accountability import build_board_action_accountability
from .governance_risk import summarize_risk_register
from .governance_control_intelligence import build_control_intelligence
from .compliance_intelligence import build_compliance_intelligence

def build_executive_governance_command_centre(*, tasks=None, actions=None, risks=None, obligations=None, meetings=None, controls=None, control_tests=None):
    base=build_governance_intelligence(tasks=tasks,actions=actions,risks=risks,obligations=obligations,meetings=meetings)
    accountability=build_board_action_accountability(actions or [])
    risk=summarize_risk_register(risks or [])
    control=build_control_intelligence(controls or [],risks or [],control_tests or [])
    compliance=build_compliance_intelligence(obligations or [])
    queue=list(base.get("priority_queue",[]))
    queue.extend({"type":"Control","id":c.get("control_id"),"title":c.get("title"),"owner":c.get("owner"),"priority":"High","reason":c.get("status")} for c in control.get("attention_controls",[]))
    queue.extend({"type":"Compliance","id":i.get("id"),"title":i.get("title"),"owner":i.get("owner"),"priority":i.get("priority"),"reason":"; ".join(i.get("reasons",[]))} for i in compliance.get("attention_items",[]))
    priority_order={"Critical":0,"High":1,"Medium":2,"Low":3}
    queue.sort(key=lambda x:(priority_order.get(x.get("priority"),9),str(x.get("title") or "")))
    return {"governance_kpis":base["kpis"],"board_action_accountability":accountability,"risk_register":risk,
      "control_intelligence":control,"compliance_intelligence":compliance,"executive_priority_queue":queue,
      "summary":{"priority_items":len(queue),"critical_risks":risk["risk_level_counts"]["Critical"],
        "high_risks":risk["risk_level_counts"]["High"],"overdue_board_actions":accountability["overdue"],
        "overdue_compliance":compliance["overdue"],"ineffective_controls":control["controls_ineffective"]}}
