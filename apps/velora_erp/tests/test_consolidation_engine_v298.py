"""Group consolidation arithmetic: translation, mapping, eliminations, ownership and honest checks."""
from decimal import Decimal as D

from velora_erp.finance.consolidation import consolidate


def acct(account, code, root, bal, label=None): return {"account": account, "code": code, "label": label or account, "root_type": root, "balance": D(bal)}


def parent(cur="NGN", rates=None):
    return {"company_id": "P", "name": "Parent Ltd", "currency": cur, "ownership": 100, "method": "Full", "rates": rates or {"closing": 1, "average": 1, "equity": 1, "opening": 1},
            "accounts": [acct("Cash", "1000", "Asset", 600), acct("Receivable IC", "1200", "Asset", 100), acct("Investment in S", "1500", "Asset", 400), acct("Share Capital", "3000", "Equity", -800), acct("Sales", "4000", "Income", -300), acct("Costs", "5000", "Expense", 100), acct("Payable", "2000", "Liability", -100)]}


def sub(ownership=100, rates=None, cur="NGN"):
    return {"company_id": "S", "name": "Sub Ltd", "currency": cur, "ownership": ownership, "method": "Full", "rates": rates or {"closing": 1, "average": 1, "equity": 1, "opening": 1},
            "accounts": [acct("Cash", "1000", "Asset", 650), acct("Payable IC", "2100", "Liability", -100), acct("Share Capital", "3000", "Equity", -500), acct("Sales", "4000", "Income", -200), acct("Costs", "5000", "Expense", 150)]}


def test_combines_by_code_and_balances_without_eliminations():
    r = consolidate([parent(), sub()], currency="NGN")
    cash = next(l for l in r["lines"] if l["key"] == "1000")
    assert cash["total"] == D(1250) and cash["cells"] == {"P": D(600), "S": D(650)}
    assert r["ok"] and abs(sum(l["total"] for l in r["lines"])) == 0
    assert r["income_statement"]["profit"] == D(250)                                  # 500 income less 250 costs


def test_intercompany_balances_and_investment_are_eliminated_and_every_entry_balances():
    rules = [{"description": "Intercompany loan", "rule_type": "Intercompany balance", "company_one": "P", "account_one": "1200", "company_two": "S", "account_two": "2100"},
             {"description": "Investment vs capital", "rule_type": "Investment", "company_one": "P", "account_one": "1500", "company_two": "S", "account_two": "3000"}]
    r = consolidate([parent(), sub()], currency="NGN", rules=rules)
    by = {l["key"]: l for l in r["lines"]}
    assert by["1200"]["total"] == 0 and by["2100"]["total"] == 0                     # the loan is gone from both sides
    assert by["1500"]["total"] == 0 and by["3000"]["total"] == D(-900)               # 1,300 of capital; the matching 400 is eliminated against the investment
    assert all(e["entry_one"] + e["entry_two"] == 0 for e in r["eliminations"])
    assert r["ok"], r["checks"]


def test_a_difference_between_the_two_sides_is_reported_not_hidden():
    s = sub(); s["accounts"][1]["balance"] = D(-90)
    s["accounts"][0]["balance"] = D(640)
    rules = [{"description": "Intercompany loan", "company_one": "P", "account_one": "1200", "company_two": "S", "account_two": "2100"}]
    r = consolidate([parent(), s], currency="NGN", rules=rules, tolerance=D(1))
    diff = [c for c in r["checks"] if c["code"] == "difference"]
    assert diff and "10.00" in diff[0]["message"]
    by = {l["key"]: l for l in r["lines"]}
    assert by["1200"]["total"] == D(10) and by["2100"]["total"] == 0                 # 90 eliminated, 10 left visible on the parent's side


def test_both_sides_on_the_same_side_is_an_error():
    s = sub(); s["accounts"][1]["balance"] = D(100); s["accounts"][0]["balance"] = D(450)
    r = consolidate([parent(), s], currency="NGN", rules=[{"description": "x", "company_one": "P", "account_one": "1200", "company_two": "S", "account_two": "2100"}])
    assert any(c["code"] == "rule_same_side" for c in r["checks"]) and not r["ok"]


def test_foreign_member_is_translated_with_closing_average_and_equity_rates_and_the_difference_goes_to_reserve():
    usd = {"company_id": "U", "name": "US Inc", "currency": "USD", "ownership": 100, "method": "Full", "rates": {"closing": 1500, "average": 1400, "equity": 1200, "opening": 1300},
           "accounts": [acct("Cash", "1000", "Asset", 100), acct("Capital", "3000", "Equity", -60), acct("Sales", "4000", "Income", -50), acct("Costs", "5000", "Expense", 10)], "prior_pl": D(0)}
    r = consolidate([usd], currency="NGN")
    by = {l["key"]: l for l in r["lines"]}
    assert by["1000"]["total"] == D(150000) and by["3000"]["total"] == D(-72000) and by["4000"]["total"] == D(-70000) and by["5000"]["total"] == D(14000)
    assert by["~CTA"]["total"] == D(-22000)                                           # 150000 - 72000 - 70000 + 14000 = 22000 left; reserve takes it
    assert r["ok"] and r["balance_sheet"]["check"] == 0


def test_results_of_earlier_periods_keep_the_balance_sheet_in_balance():
    p = {"company_id": "P", "name": "P", "currency": "NGN", "ownership": 100, "method": "Full", "rates": {"closing": 1}, "prior_pl": D(-70),
         "accounts": [acct("Cash", "1000", "Asset", 100), acct("Capital", "3000", "Equity", -30)]}
    r = consolidate([p], currency="NGN")
    assert r["ok"] and r["balance_sheet"]["check"] == 0
    assert any(l["key"] == "~PRIOR" and l["total"] == D(-70) for l in r["lines"])


def test_proportionate_share_scales_every_figure_and_full_reports_the_non_controlling_part():
    s = sub(ownership=60); s["method"] = "Proportionate"
    r = consolidate([s], currency="NGN")
    assert {l["key"]: l["total"] for l in r["lines"]}["1000"] == D(390)
    s2 = sub(ownership=80)
    r2 = consolidate([s2], currency="NGN")
    assert r2["income_statement"]["profit"] == D(50) and r2["income_statement"]["non_controlling_profit"] == D(10)
    assert r2["balance_sheet"]["non_controlling_interest"] == D(110)                   # 20% of net assets of 550


def test_mapping_overrides_a_code_and_unbalanced_members_are_flagged():
    s = sub(); s["accounts"][0]["balance"] = D(700)                                   # ledger out by 50
    r = consolidate([parent(), s], currency="NGN", mappings=[{"company_id": "S", "account": "Cash", "group_code": "1100", "group_name": "Bank"}])
    assert any(l["key"] == "1100" and l["label"] == "Bank" for l in r["lines"])
    assert any(c["code"] == "member_unbalanced" for c in r["checks"]) and not r["ok"]


def test_root_type_conflict_between_members_is_an_error():
    s = sub(); s["accounts"][0]["root_type"] = "Liability"
    r = consolidate([parent(), s], currency="NGN")
    assert any(c["code"] == "root_conflict" for c in r["checks"])
