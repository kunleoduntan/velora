import pytest
from velora_governance.governance.services.governance_risk import score_governance_risk, summarize_risk_register

def test_weighted_score_and_level():
    r=score_governance_risk([{"name":"Compliance","value":80},{"name":"Controls","value":20}],weights={"Compliance":3,"Controls":1})
    assert r["risk_score"] == 65 and r["risk_level"] == "Moderate"

def test_invalid_factor_and_weight():
    with pytest.raises(ValueError): score_governance_risk([{"name":"x","value":101}])
    with pytest.raises(ValueError): score_governance_risk([{"name":"x","value":50,"weight":-1}])

def test_register_summary():
    r=summarize_risk_register([{"risk_level":"Critical"},{"risk_level":"High"},{"risk_level":"Low","status":"Closed"}])
    assert r["high_priority_risks"] == 2 and r["open_risks"] == 2
