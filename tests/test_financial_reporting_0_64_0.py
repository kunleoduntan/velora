import json, pytest
from velora_erp.finance.reporting.regulatory_reporting import *

PROFILE={"profile_id":"NG-GENERIC-1","jurisdiction":"NG","regulator":"Configured regulator","framework":"Configured framework","fields":[{"code":"REV","label":"Revenue","data_type":"decimal","required":True,"taxonomy_tag":"Revenue"},{"code":"ENTITY_NAME","label":"Entity name","data_type":"string","required":True},{"code":"AUDITED","label":"Audited","data_type":"boolean","required":False}]}
P={"from_date":"2026-01-01","to_date":"2026-12-31"}
def pack():
 return build_regulatory_report_pack(profile=PROFILE,legal_entity="LE1",period=P,currency="NGN",values={"REV":"1000.50","ENTITY_NAME":"Example Ltd","AUDITED":True},source_references={"REV":"GL-REF","ENTITY_NAME":"MASTER-REF"},prepared_by="preparer",reporting_basis="IFRS")

def test_profile_and_report_pack():
 assert validate_regulatory_profile(PROFILE)["valid"]
 p=pack(); assert p["complete"] and not p["filing_submitted"]

def test_required_source_reference_blocks():
 p=build_regulatory_report_pack(profile=PROFILE,legal_entity="LE1",period=P,currency="NGN",values={"REV":"1000","ENTITY_NAME":"X"},source_references={},prepared_by="u",reporting_basis="IFRS")
 assert not p["complete"]

def test_unknown_field_rejected():
 with pytest.raises(RegulatoryReportingError): build_regulatory_report_pack(profile=PROFILE,legal_entity="LE1",period=P,currency="NGN",values={"BAD":1},source_references={},prepared_by="u",reporting_basis="IFRS")

def test_json_and_csv_exports():
 p=pack(); assert json.loads(export_regulatory_json(p))["profile_id"]==PROFILE["profile_id"]
 csv=export_regulatory_csv(p); assert "REV,Revenue,1000.50" in csv

def test_duplicate_profile_field_rejected():
 bad={**PROFILE,"fields":PROFILE["fields"]+[PROFILE["fields"][0]]}
 with pytest.raises(RegulatoryReportingError): validate_regulatory_profile(bad)
