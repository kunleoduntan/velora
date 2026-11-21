from datetime import date
import pytest
from velora.exceptions import ValidationError
from velora_erp.finance import gl_review as glr


def line(acct, root, d, debit=0, credit=0, doc="Journal Entry Voucher", name="J1", event="Original", desc=""):
    return {"account": acct, "account_code_snapshot": acct[:4], "account_name_snapshot": acct, "root_type_snapshot": root, "posting_date": d, "base_debit": debit, "base_credit": credit,
            "source_doctype": doc, "source_name": name, "posting_event": event, "line_description": desc}


def test_bad_periods_are_refused():
    with pytest.raises(ValidationError, match="overlaps"):
        glr.run_review("2026-01-01", "2026-06-30", "2026-03-01", "2026-04-30")
    with pytest.raises(ValidationError, match="cannot end before"):
        glr.run_review("2026-06-30", "2026-01-01", "2025-01-01", "2025-06-30")
    with pytest.raises(ValidationError, match="must look like"):
        glr.run_review("nope", "2026-01-01", "2025-01-01", "2025-06-30")


def test_review_flags_changes_odd_journals_and_clustering(monkeypatch):
    prior = [line("Rent", "Expense", date(2025, 3, 3), 100000, name="P1"), line("Sales", "Income", date(2025, 3, 3), 0, 900000, name="P2"), line("Old", "Expense", date(2025, 5, 5), 200000, name="P3"),
             line("Steady", "Expense", date(2025, 4, 4), 500000, name="P4")]
    current = [line("Rent", "Expense", date(2026, 3, 2), 400000, name="C1"),                                   # +300%
               line("Sales", "Income", date(2026, 3, 2), 50000, 0, name="C2"),                                  # income with a net debit
               line("Steady", "Expense", date(2026, 4, 6), 520000, name="C3"),                                  # +4%: quiet
               line("Brand New", "Asset", date(2026, 6, 10), 750000, name="C4"),
               line("Suspense Account", "Liability", date(2026, 6, 14), 0, 30000, name="C5", desc="unknown deposit"),
               line("Weekend Round", "Expense", date(2026, 3, 7), 300000, name="C6"),                           # a Saturday, round
               line("Month End Rush", "Expense", date(2026, 7, 31), 900000, name="C7", doc="Sales Invoice"),
               line("Month End Rush", "Expense", date(2026, 7, 2), 100000, name="C8", doc="Sales Invoice")]
    monkeypatch.setattr(glr, "_rows", lambda a, b: current if a.year == 2026 else prior)
    r = glr.run_review("2026-01-01", "2026-12-31", "2025-01-01", "2025-12-31", threshold_pct=50, min_amount=10000)
    why = {a["account"]: a["reasons"] for a in r["flagged_accounts"]}
    assert any("300.0% increase" in x for x in why["Rent"])
    assert any("net debit" in x for x in why["Sales"])
    assert "Steady" not in why and any("New account" in x for x in why["Brand New"]) and any("silent" in x for x in why["Old"])
    assert [s["account"] for s in r["suspense"]] == ["Suspense Account"]
    j = {x["document"]: x["reasons"] for x in r["journals"]}
    assert "Round amount" in j["Journal Entry Voucher C6"] and "Posted on a weekend" in j["Journal Entry Voucher C6"]
    july = next(m for m in r["period_end"] if m["month"] == "2026-07")
    assert july["share_percent"] == 90.0 and "last three days" in july["reason"]
    assert r["summary"]["flagged"] == len(r["flagged_accounts"])
