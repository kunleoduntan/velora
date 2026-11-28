"""The Python evaluator against a corpus whose expected values were produced by REAL JavaScript (see the header of the file). The Desk's TypeScript evaluator runs the same file."""
import json
from pathlib import Path

import pytest

from velora.meta.conditions import ConditionError, evaluate_condition, validate_condition

CASES = json.loads((Path(__file__).parent / "fixtures" / "conditions_corpus.json").read_text())


@pytest.mark.parametrize("c", CASES, ids=[str(c["id"]) for c in CASES])
def test_corpus(c):
    if not c["valid"]:
        with pytest.raises(ConditionError):
            validate_condition(c["expr"])
        assert evaluate_condition(c["expr"], c["doc"], c["ctx"]) is False
        return
    validate_condition(c["expr"])
    assert evaluate_condition(c["expr"], c["doc"], c["ctx"]) is c["expect"], c["expr"]


def test_corpus_is_substantial():
    assert len(CASES) >= 150 and sum(1 for c in CASES if not c["valid"]) >= 20


def test_no_eval_is_used():
    src = (Path(__file__).parents[1] / "velora" / "meta" / "conditions.py").read_text()
    assert "eval(" not in src.replace("_eval(", "").replace("evaluate_condition(", "").replace("`eval:", "")
    assert "import ast" not in src and "exec(" not in src and "__import__" not in src and "getattr(" in src and "callable(" in src
