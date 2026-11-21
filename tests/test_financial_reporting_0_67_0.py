import pytest
from velora_erp.finance.reporting.production_readiness import *

def all_controls(): return {key:True for key in REQUIRED_CONTROLS}

def test_production_readiness_requires_every_control():
 r=assess_reporting_deployment(controls=all_controls(),environment="production",database_engine="postgresql")
 assert r["qualified"] and not r["certification_claimed"]

def test_missing_controls_block_qualification():
 c=all_controls(); c["audit_store_append_only"]=False
 r=assess_reporting_deployment(controls=c,environment="production",database_engine="postgresql")
 assert not r["qualified"] and any(x["control"]=="audit_store_append_only" for x in r["missing_controls"])

def test_unqualified_database_blocks():
 r=assess_reporting_deployment(controls=all_controls(),environment="production",database_engine="sqlite")
 assert not r["qualified"]

def test_environment_validation():
 with pytest.raises(ValueError): assess_reporting_deployment(controls={},environment="prod",database_engine="postgresql")

def test_external_distribution_requires_approval():
 r=validate_reporting_job(job={"report_type":"profit_loss","recipients":["finance@example.com"],"external_delivery":True},allowed_report_types=["profit_loss"])
 assert not r["valid"] and not r["execution_authorised"]

def test_sensitive_distribution_requires_approval():
 r=validate_reporting_job(job={"report_type":"balance_sheet","recipients":["cfo@example.com"],"include_sensitive_data":True},allowed_report_types=["balance_sheet"])
 assert not r["valid"]

def test_valid_scheduled_report_is_only_validated_not_executed():
 r=validate_reporting_job(job={"report_type":"cash_flow","recipients":["cfo@example.com"]},allowed_report_types=["cash_flow"])
 assert r["valid"] and not r["execution_authorised"]

def test_duplicate_recipients_rejected():
 r=validate_reporting_job(job={"report_type":"cash_flow","recipients":["a@example.com","a@example.com"]},allowed_report_types=["cash_flow"])
 assert not r["valid"]
