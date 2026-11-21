from datetime import date
import pytest
import velora
from velora import new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_cash_transactions import setup_cash, approve, MAKER, APPROVER
from velora.permissions import Session

ADMIN = Session("setup@example.test", frozenset({"System Manager"}))
T = date.today()


def _receipt(accounts):
    with session_as(MAKER):
        return new_doc("Receipt", receipt_date=T, posting_date=T, purpose="Other Income", currency="NGN", exchange_rate=1,
                       cash_account=accounts["1000"].name, narration="x", lines=[{"account": accounts["4000"].name, "amount": 10}]).insert()


def test_rule_renames_documents_with_year_and_restarts_by_prefix(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        assert _receipt(accounts).name == "REC-00000001"               # built-in series until a rule exists
        with session_as(ADMIN):
            rule = new_doc("Naming Series Rule", document_type="Receipt", pattern="RCT-.YYYY.-.#####").insert()
        assert rule.example == f"RCT-{T.year}-00001"
        assert _receipt(accounts).name == f"RCT-{T.year}-00001"
        assert _receipt(accounts).name == f"RCT-{T.year}-00002"
        with session_as(ADMIN):
            rule.reload(); rule.enabled = 0; rule.save()
        assert _receipt(accounts).name == "REC-00000002"               # disabled: back to the built-in series, counter continues
    finally:
        velora.shutdown()


def test_rule_validation(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        with session_as(ADMIN):
            for dt, pat, msg in [("Nope", "X-.#####", "not a known"), ("Receipt", "X-.##", "counter of 3 to 12"),
                                 ("Receipt", "X-{YEAR}-.#####", "counter of 3 to 12"), ("Customer", "C-.#####", "named from")]:
                with pytest.raises(ValidationError, match=msg):
                    new_doc("Naming Series Rule", document_type=dt, pattern=pat).insert()
    finally:
        velora.shutdown()
