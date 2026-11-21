import pytest
from decimal import Decimal
from velora_erp.finance.reporting.consolidation_accounting import *

def test_acquisition_goodwill_partial_nci():
 r=calculate_acquisition_accounting(acquiree="Sub",acquisition_date="2026-01-01",consideration_transferred="800",fair_value_identifiable_net_assets="700",ownership_percentage="80")
 assert r["nci_at_acquisition"]==Decimal("140") and r["goodwill"]==Decimal("240") and not r["journal_posted"]

def test_full_goodwill_fair_value_nci():
 r=calculate_acquisition_accounting(acquiree="Sub",acquisition_date="2026-01-01",consideration_transferred="800",fair_value_identifiable_net_assets="700",ownership_percentage="80",nci_measurement="fair_value",nci_fair_value="160")
 assert r["goodwill"]==Decimal("260")

def test_control_assessment_and_override():
 assert assess_control(voting_interest="60")["control_exists"]
 assert not assess_control(voting_interest="40")["control_exists"]
 with pytest.raises(ConsolidationAccountingError): calculate_acquisition_accounting(acquiree="S",acquisition_date="2026-01-01",consideration_transferred=1,fair_value_identifiable_net_assets=1,ownership_percentage=100,control_assessment={"control_exists":False})

def test_nci_post_acquisition_movement():
 r=calculate_post_acquisition_nci(post_acquisition_net_assets_movement="100",ownership_percentage="80")
 assert r["parent_share"]==Decimal("80") and r["nci_share"]==Decimal("20") and r["reconciles"]

def test_nested_effective_ownership():
 r=validate_ownership_tree(parent_entity="P",subsidiaries=[{"entity_id":"A","parent_entity":"P","ownership_percentage":"80"},{"entity_id":"B","parent_entity":"A","ownership_percentage":"75"}])
 assert r["valid"] and r["effective_parent_ownership"]["B"]==Decimal("60.00")

def test_cycle_blocks():
 r=validate_ownership_tree(parent_entity="P",subsidiaries=[{"entity_id":"A","parent_entity":"B","ownership_percentage":"80"},{"entity_id":"B","parent_entity":"A","ownership_percentage":"75"}])
 assert not r["valid"]

def test_bad_nci_measurement_requires_fair_value():
 with pytest.raises(ConsolidationAccountingError): calculate_acquisition_accounting(acquiree="S",acquisition_date="2026-01-01",consideration_transferred=10,fair_value_identifiable_net_assets=10,ownership_percentage=80,nci_measurement="fair_value")
