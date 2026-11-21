import time

import pytest

from velora.exceptions import ValidationError
from velora.reporting.layouts import _eval_formula, _arithmetic


@pytest.mark.parametrize("f,v,exp", [("[A]+[B]", {"A": 2, "B": 3}, 5), ("[A]*[B]-1", {"A": 2, "B": 3}, 5), ("([A]+[B])/2", {"A": 2, "B": 4}, 3), ("-[A]", {"A": 2}, -2), ("[A]/[B]", {"A": 1, "B": 0}, 0)])
def test_arithmetic(f, v, exp):
    assert _eval_formula(f, v) == exp


@pytest.mark.parametrize("bad", ["2**99999999", "9**9**9", "1 if 1 else 2", "__import__('os')", "(1,2)", "1;2", "abs(1)", "1//2", "1%2", "1<2", "True"])
def test_everything_else_is_refused(bad):
    with pytest.raises(ValidationError):
        _arithmetic(bad)


def test_power_is_refused_fast():
    t = time.time()
    with pytest.raises(ValidationError):
        _eval_formula("[A]**99999999", {"A": 9})
    assert time.time() - t < 1


def test_deep_nesting_is_refused_not_crashed():
    with pytest.raises(ValidationError):
        _arithmetic("(" * 5000 + "1" + ")" * 5000)


def test_long_sum_of_50_rows_is_fine():
    assert _arithmetic("+".join(["1"] * 50)) == 50
