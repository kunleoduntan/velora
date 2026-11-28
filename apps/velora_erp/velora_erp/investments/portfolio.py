"""The portfolio picture: what is held, where, how concentrated, what matures and what is due. Read-only."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from velora import get_list

from . import calculations as calc
from .settings import get_settings

D, money = calc.D, calc.money
BUCKETS = (("Within 30 days", 30), ("31 to 90 days", 90), ("91 to 180 days", 180), ("181 to 365 days", 365), ("Over a year", 10**6))


def _base(inv, field):
    return D(inv.get(field)) * (D(inv.get("exchange_rate")) or Decimal(1))


def _pct(part, whole):
    return float(money(D(part) / D(whole) * 100)) if D(whole) else 0.0


def portfolio(as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    s = get_settings()
    fields = ["name", "investment_name", "investment_class", "asset_group", "counterparty", "status", "currency", "exchange_rate", "start_date", "maturity_date", "interest_rate", "effective_yield",
              "carrying_amount", "cost_basis", "accrued_receivable", "income_received", "wht_suffered", "expected_gross_income", "units_held", "next_payment_date", "measurement"]
    held = [r for r in get_list("Investment", filters={"docstatus": 1}, fields=fields, limit=100000, ignore_permissions=True) if r["status"] in ("Active", "Part Disposed")]
    total = sum((_base(r, "carrying_amount") for r in held), Decimal(0))
    cost = sum((_base(r, "cost_basis") for r in held), Decimal(0))
    accrued = sum((_base(r, "accrued_receivable") for r in held), Decimal(0))

    def group_by(key):
        acc: dict[str, Decimal] = {}
        for r in held:
            acc[r[key] or "Other"] = acc.get(r[key] or "Other", Decimal(0)) + _base(r, "carrying_amount")
        return [{"label": k, "amount": float(money(v)), "percent": _pct(v, total)} for k, v in sorted(acc.items(), key=lambda kv: -kv[1])]

    by_group, by_class, by_cpty = group_by("asset_group"), group_by("investment_class"), group_by("counterparty")
    cap_c, cap_g = float(s.get("max_counterparty_percent") or 0), float(s.get("max_asset_group_percent") or 0)
    alerts = []
    for row in by_cpty:
        row["over_limit"] = bool(cap_c and row["percent"] > cap_c)
        if row["over_limit"]:
            alerts.append({"kind": "concentration", "severity": "warning", "message": f"{row['label']} holds {row['percent']:.1f}% of the portfolio (limit {cap_c:.0f}%)."})
    for row in by_group:
        row["over_limit"] = bool(cap_g and row["percent"] > cap_g)
        if row["over_limit"]:
            alerts.append({"kind": "concentration", "severity": "warning", "message": f"{row['label']} is {row['percent']:.1f}% of the portfolio (limit {cap_g:.0f}%)."})

    ladder = [{"label": name, "amount": 0.0, "count": 0} for name, _ in BUCKETS]
    upcoming, holdings = [], []
    horizon = int(s.get("maturity_alert_days") or 30)
    weighted = Decimal(0)
    for r in held:
        base = _base(r, "carrying_amount")
        weighted += base * D(r["effective_yield"])
        days = (r["maturity_date"] - as_of).days if r.get("maturity_date") else None
        if days is not None and calc.is_fixed_income(r["investment_class"]):
            for i, (_, limit) in enumerate(BUCKETS):
                if days <= limit:
                    ladder[i]["amount"] = float(money(D(ladder[i]["amount"]) + base))
                    ladder[i]["count"] += 1
                    break
            if days < 0:
                alerts.append({"kind": "overdue", "severity": "critical", "message": f"{r['investment_name']} passed its maturity date ({r['maturity_date']}) and has not been closed."})
            elif days <= horizon:
                alerts.append({"kind": "maturity", "severity": "info", "message": f"{r['investment_name']} matures in {days} days ({r['maturity_date']})."})
            upcoming.append({"date": str(r["maturity_date"]), "event": "Maturity", "investment": r["name"], "name": r["investment_name"], "amount": float(money(base))})
        if r.get("next_payment_date") and r["next_payment_date"] <= as_of + timedelta(days=60):
            upcoming.append({"date": str(r["next_payment_date"]), "event": "Income due", "investment": r["name"], "name": r["investment_name"], "amount": 0.0})
        holdings.append({"name": r["name"], "investment_name": r["investment_name"], "investment_class": r["investment_class"], "counterparty": r["counterparty"], "carrying_amount": float(money(base)),
                         "effective_yield": float(D(r["effective_yield"])), "maturity_date": str(r["maturity_date"]) if r.get("maturity_date") else None, "days_to_maturity": days,
                         "accrued_receivable": float(money(_base(r, "accrued_receivable"))), "measurement": r["measurement"]})
    upcoming = sorted([u for u in upcoming if u["date"] <= str(as_of + timedelta(days=90))], key=lambda u: u["date"])[:15]
    year_start = date(as_of.year, 1, 1)
    income = tax = Decimal(0)
    for t in get_list("Investment Transaction", filters={"docstatus": 1, "status": "Posted"}, fields=["transaction_date", "d_accrued", "d_wht", "investment"], limit=200000, ignore_permissions=True):
        if year_start <= t["transaction_date"] <= as_of:
            income += D(t["d_accrued"])
            tax += D(t["d_wht"])
    return {
        "as_of": str(as_of), "currency_note": "Amounts are in the company's base currency (carrying amount x the investment's exchange rate).",
        "kpis": {"carrying": float(money(total)), "cost": float(money(cost)), "unrealised": float(money(total - cost)), "accrued_receivable": float(money(accrued)), "income_ytd": float(money(income)),
                 "tax_withheld_ytd": float(money(tax)), "weighted_yield": float(money(weighted / total)) if total else 0.0, "holdings": len(held)},
        "by_group": by_group, "by_class": by_class, "by_counterparty": by_cpty[:10], "ladder": ladder, "upcoming": upcoming, "holdings": sorted(holdings, key=lambda h: -h["carrying_amount"]),
        "alerts": alerts, "limits": {"counterparty_percent": cap_c, "asset_group_percent": cap_g},
    }
