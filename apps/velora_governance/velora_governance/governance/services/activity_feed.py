"""ERP -> emissions activity feed (spend-based, GHG Protocol Scope 3 category 1/2 and similar).

Reads submitted Purchase Invoice lines for a reporting period, classifies each line with the entity's Spend Emission Rules
(first match by priority, then specificity), and writes ONE GHG Calculation per rule carrying the total spend. Re-running
recomputes the period from the invoices and refreshes those calculations, so it cannot double count. Spend that no rule
covers is reported, not guessed: the run shows coverage.

Spend-based estimates are the lowest-quality method in the GHG Protocol hierarchy; the calculations are labelled so.
"""
from __future__ import annotations

from decimal import Decimal

from velora import get_doc, get_list, new_doc, throw

SOURCE_DOCTYPE = "Purchase Invoice"
D = Decimal


def _dec(value) -> Decimal:
    try:
        return D(str(value or 0))
    except Exception:
        return D(0)


def matchers(rule: dict) -> int:
    return sum(1 for k in ("match_account", "match_item_group", "match_item", "match_supplier") if rule.get(k))


def rule_matches(rule: dict, line: dict) -> bool:
    for key, field in (("match_account", "account"), ("match_item_group", "item_group"), ("match_item", "item_code"), ("match_supplier", "supplier")):
        wanted = rule.get(key)
        if wanted and (line.get(field) or "") != wanted:
            return False
    mode = rule.get("fixed_assets") or "Any"
    asset = bool(line.get("is_fixed_asset"))
    if mode == "Fixed assets only" and not asset:
        return False
    if mode == "Exclude fixed assets" and asset:
        return False
    return bool(matchers(rule))


def order_rules(rules: list[dict]) -> list[dict]:
    return sorted(rules, key=lambda r: (int(r.get("priority") or 100), -matchers(r), r.get("name") or ""))


def classify(lines: list[dict], rules: list[dict]) -> dict:
    """Pure: returns per-rule totals and the unmapped remainder. Every line lands in exactly one bucket."""
    ordered = order_rules([r for r in rules if r.get("active", 1)])
    by_rule: dict[str, dict] = {}
    unmapped: dict[str, dict] = {}
    for line in lines:
        amount = _dec(line.get("amount"))
        hit = next((r for r in ordered if rule_matches(r, line)), None)
        if hit:
            b = by_rule.setdefault(hit["name"], {"rule": hit, "lines": 0, "spend": D(0)})
            b["lines"] += 1; b["spend"] += amount
        else:
            key = line.get("account") or line.get("item_group") or line.get("item_code") or "(no account)"
            b = unmapped.setdefault(key, {"lines": 0, "spend": D(0)})
            b["lines"] += 1; b["spend"] += amount
    return {"by_rule": by_rule, "unmapped": unmapped}


def load_purchase_invoice_lines(date_from, date_to) -> tuple[list[dict], int]:
    """Submitted, non-rejected Purchase Invoice lines in the date range, with amounts in the books' base currency."""
    try:
        invoices = get_list(SOURCE_DOCTYPE, filters=[["docstatus", "=", 1], ["posting_date", ">=", str(date_from)], ["posting_date", "<=", str(date_to)]],
                            fields=["name", "party", "approval_status", "exchange_rate"], limit=100000, ignore_permissions=True)
    except Exception as exc:  # the ERP app is optional for Governance
        throw(f"Purchase Invoices cannot be read ({exc}). The activity feed needs the ERP app installed.")
    invoices = [i for i in invoices if i.get("approval_status") != "Rejected"]
    docs = [get_doc(SOURCE_DOCTYPE, i["name"], ignore_permissions=True) for i in invoices]
    codes = sorted({r.get("item_code") for d in docs for r in (d.get("lines") or []) if r.get("item_code")})
    groups = {}
    if codes:
        groups = {r["name"]: r.get("item_group") for r in get_list("Inventory Item", filters=[["name", "in", codes]], fields=["name", "item_group"], limit=100000, ignore_permissions=True)}
    out = []
    for d in docs:
        rate = _dec(d.get("exchange_rate")) or D(1)
        for r in (d.get("lines") or []):
            base = r.get("base_amount")
            amount = _dec(base) if base not in (None, 0, 0.0) else _dec(r.get("amount")) * rate
            out.append({"invoice": d.name, "supplier": d.get("party"), "account": r.get("account"), "item_code": r.get("item_code"),
                        "item_group": groups.get(r.get("item_code")), "is_fixed_asset": bool(r.get("is_fixed_asset")), "amount": amount})
    return out, len(docs)


def _period(entity, reporting_period):
    rows = get_list("Sustainability Reporting Period", filters=[["governance_entity", "=", entity], ["period_name", "=", reporting_period]],
                    fields=["period_start", "period_end"], limit=1, ignore_permissions=True)
    if not rows:
        throw(f"No Sustainability Reporting Period named '{reporting_period}' exists for this entity. Create it first: its dates decide which invoices are read.")
    return rows[0]["period_start"], rows[0]["period_end"]


def _rules(entity):
    return [dict(r) for r in get_list("Spend Emission Rule", filters=[["governance_entity", "=", entity], ["active", "=", 1]],
            fields=["name", "rule_name", "priority", "match_account", "match_item_group", "match_item", "match_supplier", "fixed_assets", "treatment",
                    "emission_source", "emission_factor", "spend_per_factor_unit", "active"], limit=1000, ignore_permissions=True)]


def build_run(entity, reporting_period, *, loader=None) -> dict:
    """Compute the feed without writing anything."""
    date_from, date_to = _period(entity, reporting_period)
    rules = _rules(entity)
    if not rules:
        throw("This entity has no active Spend Emission Rules. Add rules that map accounts, item groups or items to an emission source and a spend-based factor.")
    lines, invoice_count = (loader or load_purchase_invoice_lines)(date_from, date_to)
    c = classify(lines, rules)
    results, estimated, excluded = [], D(0), D(0)
    for name, b in c["by_rule"].items():
        r = b["rule"]
        if r["treatment"] == "Exclude from inventory":
            excluded += b["spend"]
            results.append({"outcome": "Excluded", "rule": r.get("rule_name") or name, "rule_name": name, "key": "", "lines": b["lines"], "spend": b["spend"]})
        else:
            estimated += b["spend"]
            results.append({"outcome": "Estimated", "rule": r.get("rule_name") or name, "rule_name": name, "key": "", "lines": b["lines"], "spend": b["spend"],
                            "emission_source": r["emission_source"], "emission_factor": r["emission_factor"],
                            "quantity": b["spend"] / _dec(r["spend_per_factor_unit"])})
    unmapped = D(0)
    for key, b in sorted(c["unmapped"].items(), key=lambda kv: -kv[1]["spend"]):
        unmapped += b["spend"]
        results.append({"outcome": "Unmapped", "rule": "", "rule_name": "", "key": key, "lines": b["lines"], "spend": b["spend"]})
    total = estimated + excluded + unmapped
    warnings = []
    if unmapped > 0 and total > 0:
        warnings.append(f"{(unmapped / total * 100):.1f}% of spend has no rule. It is NOT in the inventory; add rules or exclusions for the larger accounts below.")
    return {"governance_entity": entity, "reporting_period": reporting_period, "date_from": str(date_from), "date_to": str(date_to),
            "invoices": invoice_count, "lines_total": len(lines), "spend_total": total, "spend_estimated": estimated, "spend_excluded": excluded,
            "spend_unmapped": unmapped, "coverage_percent": (estimated + excluded) / total * 100 if total else D(100), "results": results, "warnings": warnings}


def _plain(run: dict) -> dict:
    def conv(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v
    return conv(run)


def preview(entity, reporting_period, *, loader=None) -> dict:
    return _plain(build_run(entity, reporting_period, loader=loader))


def post(entity, reporting_period, *, loader=None, user=None) -> dict:
    """Write or refresh the period's spend-based GHG Calculations. Refused when assurance has locked the period."""
    from velora_governance.governance.services.assurance_lock import assert_unlocked
    assert_unlocked(entity, reporting_period, "The activity feed")
    run = build_run(entity, reporting_period, loader=loader)
    prefix = f"{entity}|{reporting_period}|"
    estimated = [r for r in run["results"] if r["outcome"] == "Estimated"]
    for r in estimated:
        src = get_list("Emission Source", filters=[["name", "=", r["emission_source"]]], fields=["active", "unit"], limit=1, ignore_permissions=True)
        if not src or not src[0].get("active", 1):
            throw(f"Rule '{r['rule']}' points to an inactive or missing Emission Source.")
    manual = {c["emission_source"] for c in get_list("GHG Calculation", filters=[["governance_entity", "=", entity], ["reporting_period", "=", reporting_period]],
              fields=["emission_source", "feed_key"], limit=100000, ignore_permissions=True) if not c.get("feed_key")}
    for r in estimated:
        if r["emission_source"] in manual:
            run["warnings"].append(f"Emission Source {r['emission_source']} also has hand-entered calculations for this period; check that the same activity is not counted twice.")
    doc = new_doc("Activity Feed Run", governance_entity=entity, reporting_period=reporting_period, date_from=run["date_from"], date_to=run["date_to"],
                  source_doctype=SOURCE_DOCTYPE, run_status="Posted", invoices=run["invoices"], lines_total=run["lines_total"],
                  spend_total=float(run["spend_total"]), spend_estimated=float(run["spend_estimated"]), spend_excluded=float(run["spend_excluded"]),
                  spend_unmapped=float(run["spend_unmapped"]), coverage_percent=float(run["coverage_percent"]), warnings="\n".join(run["warnings"]), run_by=user)
    doc.insert(ignore_permissions=True)
    keep, total_t = set(), D(0)
    out_rows = []
    for r in run["results"]:
        row = {"outcome": r["outcome"], "rule": r["rule"], "key": r["key"], "lines": r["lines"], "spend": float(r["spend"])}
        if r["outcome"] == "Estimated":
            key = prefix + r["rule_name"]; keep.add(key)
            unit = get_list("Emission Source", filters=[["name", "=", r["emission_source"]]], fields=["unit"], limit=1, ignore_permissions=True)[0]["unit"]
            existing = get_list("GHG Calculation", filters=[["feed_key", "=", key]], fields=["name"], limit=1, ignore_permissions=True)
            values = dict(governance_entity=entity, emission_source=r["emission_source"], reporting_period=reporting_period, activity_quantity=float(r["quantity"]),
                          unit=unit, emission_factor=r["emission_factor"], methodology=f"Spend-based from {SOURCE_DOCTYPE} ({run['lines_total']} lines read), run {doc.name}",
                          feed_key=key, feed_run=doc.name)
            if existing:
                calc = get_doc("GHG Calculation", existing[0]["name"], ignore_permissions=True)
                for k, v in values.items():
                    calc.set(k, v)
                calc.save(ignore_permissions=True)
            else:
                calc = new_doc("GHG Calculation", **values); calc.insert(ignore_permissions=True)
            row["ghg_calculation"] = calc.name
            total_t += D(str(calc.emissions_tco2e or 0))
        out_rows.append(row)
    for stale in get_list("GHG Calculation", filters=[["governance_entity", "=", entity], ["reporting_period", "=", reporting_period]], fields=["name", "feed_key"], limit=100000, ignore_permissions=True):
        if stale.get("feed_key") and stale["feed_key"] not in keep:
            get_doc("GHG Calculation", stale["name"], ignore_permissions=True).delete(ignore_permissions=True)
    doc = get_doc("Activity Feed Run", doc.name, ignore_permissions=True)
    doc.emissions_tco2e = float(total_t)
    doc.set("results", out_rows)
    doc.save(ignore_permissions=True)
    out = _plain(run); out["run"] = doc.name; out["emissions_tco2e"] = float(total_t)
    return out
