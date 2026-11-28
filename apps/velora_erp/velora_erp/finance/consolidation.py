"""Group consolidation: member trial balances in, one consolidated worksheet and statements out. Pure arithmetic, no database.

Each company keeps its own database, so this engine never reads across them itself: `consolidation_service` collects every member's
balances (through that company's own permissions) and hands plain numbers to `consolidate`.

Sign convention everywhere in the worksheet: balance = debit - credit (assets positive, liabilities / equity / income negative).

What it does
  * translates each member into the group's presentation currency: assets and liabilities at the closing rate, income and expenses at
    the average rate, equity at the equity rate and results of earlier, not yet closed periods at the opening rate; the difference that
    translation leaves behind is carried to a currency translation reserve in equity (never hidden in another line);
  * maps accounts across members by account code (or name), with explicit overrides;
  * applies the ownership share (Proportionate) or keeps 100% and reports the non-controlling share (Full);
  * applies elimination rules (intercompany balances, income and expense, investments, dividends), each a balanced entry, and reports
    any difference left between the two sides instead of forcing it away.

What it does not do (and says so in its checks): goodwill and fair-value adjustments at acquisition, the equity method, deferred tax on
eliminations, or a different rate for each historical equity movement.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
ROOT_ORDER = ["Asset", "Liability", "Equity", "Income", "Expense"]
CTA_KEY, PRIOR_KEY = "~CTA", "~PRIOR"
CTA_LABEL, PRIOR_LABEL = "Currency translation reserve", "Results of earlier periods not yet closed"


def D(v) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except Exception:
        return Decimal(0)


def q(v) -> Decimal:
    return D(v).quantize(CENT, rounding=ROUND_HALF_UP)


def line_key(code, name) -> str:
    return (str(code or "").strip() or str(name or "").strip()).upper()


def _rate_for(root: str, rates: dict) -> Decimal:
    return D({"Income": rates.get("average"), "Expense": rates.get("average"), "Equity": rates.get("equity")}.get(root, rates.get("closing")) or rates.get("closing") or 1)


def consolidate(members: list[dict], *, currency: str, mappings: list[dict] | None = None, rules: list[dict] | None = None, tolerance=Decimal("1.00")) -> dict:
    """members: [{company_id, name, currency, ownership, method, accounts:[{account, code, label, root_type, balance}], prior_pl, rates:{closing,average,equity,opening}, notes:[]}]
    mappings: [{company_id, account, group_code, group_name}]   rules: [{description, rule_type, company_one, account_one, company_two, account_two, basis, fixed_amount}]"""
    checks: list[dict] = []
    add = lambda level, code, message, company="": checks.append({"level": level, "code": code, "message": message, "company": company})
    tolerance = D(tolerance)
    mapping = {}
    for m in mappings or []:
        if m.get("company_id") and m.get("account") and m.get("group_code"):
            mapping[(m["company_id"], str(m["account"]).strip().upper())] = (str(m["group_code"]).strip().upper(), (m.get("group_name") or "").strip())

    lines: dict[str, dict] = {}                         # key -> {key,label,root_type,cells:{company: Decimal}, elimination: Decimal}
    resolve: dict[tuple, str] = {}                      # (company, account name or code, upper) -> key, used by the elimination rules
    cells_by_member: dict[str, dict[str, Decimal]] = {}
    active = [m for m in members if m.get("include", True)]
    ids = [m["company_id"] for m in active]
    if len(set(ids)) != len(ids): add("error", "duplicate_member", "A company is listed twice in this group.")

    def line(key, label, root):
        ln = lines.get(key)
        if ln is None: ln = lines[key] = {"key": key, "label": label or key, "root_type": root, "cells": {}, "elimination": Decimal(0)}
        elif ln["root_type"] != root and not key.startswith("~"):
            add("error", "root_conflict", f"Account {key} is a {ln['root_type']} account in one company and a {root} account in another; map one of them to a different group account.")
        return ln

    profits: dict[str, Decimal] = {}; net_assets: dict[str, Decimal] = {}
    for m in active:
        cid, rates = m["company_id"], m.get("rates") or {}
        own = D(m.get("ownership", 100)); own = Decimal(100) if own <= 0 else min(own, Decimal(100))
        factor = own / 100 if m.get("method") == "Proportionate" else Decimal(1)
        cells: dict[str, Decimal] = cells_by_member.setdefault(cid, {})
        local_total = Decimal(0); any_data = False
        for a in m.get("accounts", []):
            bal = D(a.get("balance"))
            if bal == 0: continue
            any_data = True; local_total += bal
            code_map = mapping.get((cid, str(a.get("account", "")).strip().upper())) or mapping.get((cid, str(a.get("code", "")).strip().upper()))
            key, label = (code_map[0], code_map[1] or a.get("label")) if code_map else (line_key(a.get("code"), a.get("account")), a.get("label") or a.get("account"))
            root = a.get("root_type") or "Asset"
            line(key, label, root)
            cells[key] = cells.get(key, Decimal(0)) + q(bal * _rate_for(root, rates) * factor)
        prior = D(m.get("prior_pl"))
        if prior != 0:
            any_data = True; local_total += prior
            line(PRIOR_KEY, PRIOR_LABEL, "Equity"); cells[PRIOR_KEY] = q(prior * D(rates.get("opening") or rates.get("closing") or 1) * factor)
        for a in m.get("accounts", []):                  # every spelling a rule may use for this company's accounts
            code_map = mapping.get((cid, str(a.get("account", "")).strip().upper())) or mapping.get((cid, str(a.get("code", "")).strip().upper()))
            key = code_map[0] if code_map else line_key(a.get("code"), a.get("account"))
            for spelling in (a.get("account"), a.get("code"), a.get("label")):
                if spelling: resolve[(cid, str(spelling).strip().upper())] = key
        if not any_data: add("warning", "no_data", f"{m.get('name', cid)} has no posted entries for this period.", cid)
        if abs(local_total) > Decimal("0.005"): add("error", "member_unbalanced", f"{m.get('name', cid)}'s ledger does not balance (difference {q(local_total):,}); fix it in that company first.", cid)
        translated_sum = sum(cells.values(), Decimal(0))
        if translated_sum != 0:
            line(CTA_KEY, CTA_LABEL, "Equity"); cells[CTA_KEY] = cells.get(CTA_KEY, Decimal(0)) - translated_sum   # whatever translation leaves behind
        pl = sum((v for k, v in cells.items() if k in lines and lines[k]["root_type"] in ("Income", "Expense")), Decimal(0))
        profits[cid] = -pl
        net_assets[cid] = sum((v for k, v in cells.items() if k in lines and lines[k]["root_type"] in ("Asset", "Liability")), Decimal(0))
        for k, v in cells.items(): lines[k]["cells"][cid] = v

    # ---- eliminations -------------------------------------------------------------------------------------------------
    entries: list[dict] = []
    for r in rules or []:
        if r.get("enabled") is False or r.get("enabled") == 0: continue
        what = r.get("description") or r.get("rule_type") or "Elimination"
        c1, c2 = r.get("company_one"), r.get("company_two")
        k1 = resolve.get((c1, str(r.get("account_one", "")).strip().upper())); k2 = resolve.get((c2, str(r.get("account_two", "")).strip().upper()))
        if not k1 or not k2:
            add("error", "rule_account", f"{what}: account {r.get('account_one') if not k1 else r.get('account_two')} was not found in {c1 if not k1 else c2}, or has no entries.")
            continue
        v1 = cells_by_member.get(c1, {}).get(k1, Decimal(0)); v2 = cells_by_member.get(c2, {}).get(k2, Decimal(0))
        basis = r.get("basis") or "Matching balance"
        if basis == "Fixed amount": amt = abs(D(r.get("fixed_amount")))
        elif basis == "Side one balance": amt = abs(v1)
        elif basis == "Side two balance": amt = abs(v2)
        else:
            amt = min(abs(v1), abs(v2))
            if v1 and v2 and (v1 > 0) == (v2 > 0): add("error", "rule_same_side", f"{what}: both sides are on the same side of the ledger ({q(v1):,} and {q(v2):,}), so they cannot offset each other; check the two accounts.")
            if abs(abs(v1) - abs(v2)) > tolerance:
                add("warning", "difference", f"{what}: the two sides differ by {q(abs(abs(v1) - abs(v2))):,} ({c1} {q(v1):,} against {c2} {q(v2):,}); the matching part was eliminated and the difference stays visible.")
        amt = q(amt)
        if amt == 0: continue
        s1 = (1 if v1 > 0 else -1) if v1 else (-1 if v2 > 0 else 1) if v2 else (1 if basis == "Fixed amount" else 0)
        if s1 == 0: continue
        if basis == "Matching balance" and v1 and v2 and (v1 > 0) == (v2 > 0): continue
        e1, e2 = -s1 * amt, s1 * amt                     # equal and opposite, so every entry balances on its own
        lines[k1]["elimination"] += e1; lines[k2]["elimination"] += e2
        entries.append({"description": what, "rule_type": r.get("rule_type") or "", "company_one": c1, "account_one": k1, "company_two": c2, "account_two": k2, "amount": amt, "entry_one": e1, "entry_two": e2})

    # ---- totals, statements ----------------------------------------------------------------------------------------------
    out_lines = []
    for ln in sorted(lines.values(), key=lambda x: (ROOT_ORDER.index(x["root_type"]) if x["root_type"] in ROOT_ORDER else 9, x["key"].startswith("~"), x["key"])):
        total = sum(ln["cells"].values(), Decimal(0)) + ln["elimination"]
        out_lines.append({"key": ln["key"], "label": ln["label"], "root_type": ln["root_type"], "cells": dict(ln["cells"]), "elimination": ln["elimination"], "total": total})
    grand = sum((l["total"] for l in out_lines), Decimal(0))
    if abs(grand) > Decimal("0.005"): add("error", "consolidated_unbalanced", f"The consolidated trial balance is out by {q(grand):,}; do not rely on these figures until the checks above are resolved.")

    def block(root, sign):
        rows = [{"key": l["key"], "label": l["label"], "amount": sign * l["total"], "cells": {c: sign * v for c, v in l["cells"].items()}, "elimination": sign * l["elimination"]} for l in out_lines if l["root_type"] == root and l["total"] != 0 or (l["root_type"] == root and l["elimination"] != 0)]
        return {"rows": rows, "total": sum((r["amount"] for r in rows), Decimal(0))}
    income, expense = block("Income", -1), block("Expense", 1)
    profit = income["total"] - expense["total"]
    assets, liabilities, equity = block("Asset", 1), block("Liability", -1), block("Equity", -1)
    nci_profit = sum(((100 - min(D(m.get("ownership", 100)), Decimal(100))) / 100 * profits.get(m["company_id"], Decimal(0)) for m in active if m.get("method") != "Proportionate" and D(m.get("ownership", 100)) < 100), Decimal(0))
    nci_equity = sum(((100 - min(D(m.get("ownership", 100)), Decimal(100))) / 100 * net_assets.get(m["company_id"], Decimal(0)) for m in active if m.get("method") != "Proportionate" and D(m.get("ownership", 100)) < 100), Decimal(0))
    total_equity = equity["total"] + profit
    if abs(assets["total"] - liabilities["total"] - total_equity) > Decimal("0.01") and not any(c["code"] == "consolidated_unbalanced" for c in checks):
        add("error", "balance_sheet", "Assets do not equal liabilities plus equity.")
    add("info", "scope", "Goodwill, fair-value adjustments at acquisition and the equity method are not calculated; equity is translated at the equity rate you supplied (or the closing rate).")
    return {
        "currency": currency, "members": [{"company_id": m["company_id"], "name": m.get("name") or m["company_id"], "currency": m.get("currency", ""), "ownership": q(m.get("ownership", 100)), "method": m.get("method") or "Full", "rates": m.get("rates") or {}, "profit": q(profits.get(m["company_id"], 0))} for m in active],
        "lines": out_lines, "eliminations": entries,
        "income_statement": {"income": income, "expense": expense, "profit": profit, "profit_attributable_to_owners": profit - nci_profit, "non_controlling_profit": nci_profit},
        "balance_sheet": {"assets": assets, "liabilities": liabilities, "equity": equity, "current_result": profit, "total_equity": total_equity, "non_controlling_interest": nci_equity,
                          "equity_attributable_to_owners": total_equity - nci_equity, "check": assets["total"] - liabilities["total"] - total_equity},
        "checks": checks, "ok": not any(c["level"] == "error" for c in checks),
    }
