import pytest
from velora_erp.finance.reporting.disclosure_pack import build_integrated_disclosure_pack,DisclosurePackError

def test_disclosure_pack_requires_approved_statements_and_evidence():
 fields={"opening_cost":1,"additions":2,"disposals":0,"transfers":0,"closing_cost":3,"opening_accumulated_depreciation":0,"depreciation":0,"impairment":0,"disposals_accumulated_depreciation":0,"closing_accumulated_depreciation":0,"closing_carrying_amount":3}
 fields.update({k:0 for k in ("opening_accumulated_impairment","impairment_reversals","disposals_accumulated_impairment","closing_accumulated_impairment")})   # IAS 36 impairment columns became mandatory in the PPE schedule
 refs={k:"PPE-REGISTER" for k in fields}
 r=build_integrated_disclosure_pack(legal_entity="ACME",currency="NGN",period={"year":2026},notes=[{"note_code":"PPE","current":fields,"comparative":fields,"source_references":refs}],primary_statements={"SFP":{"status":"Approved"}},prepared_by="Finance")
 assert r['complete'] and r['notes'][0]['complete']

def test_disclosure_pack_blocks_unapproved_statement():
 r=build_integrated_disclosure_pack(legal_entity="ACME",currency="NGN",period={"year":2026},notes=[],primary_statements={"P&L":{"status":"Draft"}},prepared_by="Finance")
 assert not r['complete']

def test_duplicate_note_rejected():
 with pytest.raises(DisclosurePackError): build_integrated_disclosure_pack(legal_entity="A",currency="NGN",period={},notes=[{"note_code":"PPE"},{"note_code":"PPE"}],primary_statements={},prepared_by="x")
