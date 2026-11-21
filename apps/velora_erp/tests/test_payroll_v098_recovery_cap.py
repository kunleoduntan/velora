from decimal import Decimal
import pytest
from velora_erp.finance.payroll_engine import allocate_loan_recoveries, PayrollCalculationError

def test_combined_loan_cap_applies_once_across_all_loan_types():
    allocations=[
      {"employee_loan":"LN1","loan_type":"VEHICLE","amount":100,"interest_amount":10,"due_date":"2026-11-01"},
      {"employee_loan":"LN2","loan_type":"HOUSING","amount":150,"interest_amount":0,"due_date":"2026-11-01"},
    ]
    r=allocate_loan_recoveries(allocations,net_before_loan_recovery=1000,overall_percent=20)
    assert r["overall_cap"]==Decimal("200.00")
    assert r["allowed_total"]==Decimal("200.00")
    assert r["deferred_total"]==Decimal("60.00")
    assert r["net_after_loan_recovery"]==Decimal("800.00")

def test_loan_type_stricter_cap_and_priority_respected():
    allocations=[
      {"employee_loan":"LN1","loan_type":"LOW","amount":150,"interest_amount":0,"due_date":"2026-10-01"},
      {"employee_loan":"LN2","loan_type":"HIGH","amount":150,"interest_amount":0,"due_date":"2026-10-01"},
    ]
    policies={"LOW":{"maximum_deduction_percent_of_net_pay":5,"deduction_priority":1},"HIGH":{"maximum_deduction_percent_of_net_pay":0,"deduction_priority":2}}
    r=allocate_loan_recoveries(allocations,net_before_loan_recovery=1000,overall_percent=20,loan_type_policies=policies)
    by_type={k:v["allowed"] for k,v in r["type_summary"].items()}
    assert by_type["LOW"]==Decimal("50.00")
    assert by_type["HIGH"]==Decimal("150.00")

def test_minimum_net_pay_floor_additionally_limits_loan_recovery():
    r=allocate_loan_recoveries([{"employee_loan":"LN1","loan_type":"A","amount":500}],net_before_loan_recovery=600,overall_percent=80,minimum_net_pay=400)
    assert r["allowed_total"]==Decimal("200.00")
    assert r["net_after_loan_recovery"]==Decimal("400.00")

def test_partial_recovery_can_be_disabled_per_loan_type():
    r=allocate_loan_recoveries([{"employee_loan":"LN1","loan_type":"A","amount":100}],net_before_loan_recovery=100,overall_percent=50,loan_type_policies={"A":{"allow_partial_recovery":False}})
    assert r["allowed_total"]==Decimal("0.00")
    assert r["deferred_total"]==Decimal("100.00")

def test_interest_and_principal_both_count_toward_cap_and_interest_first():
    r=allocate_loan_recoveries([{"employee_loan":"LN1","loan_type":"A","amount":100,"interest_amount":20}],net_before_loan_recovery=100,overall_percent=10)
    a=r["allocations"][0]
    assert a["interest_amount"]==Decimal("10.00")
    assert a["amount"]==Decimal("0.00")

def test_invalid_cap_rejected():
    with pytest.raises(PayrollCalculationError):
        allocate_loan_recoveries([],net_before_loan_recovery=100,overall_percent=101)
