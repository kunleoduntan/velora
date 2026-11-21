from decimal import Decimal
import pytest
from velora.exceptions import ValidationError
from velora_erp.finance.landed_cost import calculate_allocations

@pytest.mark.parametrize('method,rows,expected',[
    ('By Value',[{'item_value':100},{'item_value':300}],[Decimal('25.00'),Decimal('75.00')]),
    ('By Quantity',[{'quantity':1},{'quantity':3}],[Decimal('25.00'),Decimal('75.00')]),
    ('By Weight',[{'weight':2},{'weight':2}],[Decimal('50.00'),Decimal('50.00')]),
    ('By Volume',[{'volume':1},{'volume':2}],[Decimal('33.33'),Decimal('66.67')]),
    ('Equal',[{},{}],[Decimal('50.00'),Decimal('50.00')]),
])
def test_landed_cost_allocation_methods_balance_exactly(method,rows,expected):
    result=calculate_allocations(100,rows,method)
    assert result==expected
    assert sum(result)==Decimal('100.00')

def test_landed_cost_rejects_zero_allocation_basis():
    with pytest.raises(ValidationError):
        calculate_allocations(100,[{'item_value':0},{'item_value':0}],'By Value')
