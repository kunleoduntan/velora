from velora_governance.governance.services.governance_intelligence import build_governance_intelligence

def test_kpis_priority_and_counts():
    r=build_governance_intelligence(tasks=[{"status":"Open"},{"status":"Overdue","overdue":True}], actions=[{"status":"Open","title":"Action 1"}], risks=[{"risk_level":"Critical","title":"Risk 1"}], obligations=[{"status":"Overdue","overdue":True}], meetings=[{}])
    assert r["kpis"]["overdue_items"] == 2
    assert r["kpis"]["open_actions"] == 1
    assert r["priority_queue"][0]["reason"] == "Overdue"
