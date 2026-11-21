from decimal import Decimal
import pytest
from velora_erp.finance.reporting.reconciliation_engine import (reconcile_trial_balance_to_financial_position,reconcile_cash_flow,reconcile_equity_movement,reconcile_control_account,build_reconciliation_pack,ReconciliationError)

def test_tb_to_statement_reconciles_and_flags_unmapped():
 r=reconcile_trial_balance_to_financial_position(trial_balance={"Cash":Decimal("100"),"Loan":Decimal("-100")},statement_rows=[{"code":"cash","accounts":["Cash"],"amount":"100"},{"code":"loan","accounts":["Loan"],"amount":"-100"}])
 assert r['reconciled'] and not r['unmapped_trial_balance_accounts']

def test_tb_duplicate_account_mapping_rejected():
 with pytest.raises(ReconciliationError): reconcile_trial_balance_to_financial_position(trial_balance={"A":1},statement_rows=[{"code":"x","accounts":["A"],"amount":1},{"code":"y","accounts":["A"],"amount":1}])

def test_cash_flow_reconciliation():
 r=reconcile_cash_flow(opening_cash="100",net_cash_movement="25",closing_cash_per_statement="125",closing_cash_per_ledger="125")
 assert r['reconciled']

def test_equity_movement_reconciliation():
 r=reconcile_equity_movement(opening_equity=100,profit_or_loss=20,other_comprehensive_income=0,owner_contributions=10,distributions=5,closing_equity=125)
 assert r['reconciled']

def test_subledger_difference_is_exception_not_adjustment():
 r=reconcile_control_account(control_account_balance=100,subledger_balance=95,control_account="AR",subledger_name="Receivables")
 assert r['exception_required'] and r['difference']==Decimal('5') and r['read_only']

def test_reconciliation_pack_blocks_unreconciled():
 r=build_reconciliation_pack(legal_entity="ACME",currency="NGN",period={"from":"2026-01-01","to":"2026-01-31"},reconciliations=[{"reconciled":False}],prepared_by="CFO")
 assert not r['reconciled'] and r['publication_blockers']
