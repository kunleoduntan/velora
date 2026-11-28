"""Governed project financial control and read models.

Actuals and recognised revenue are imported from authoritative source systems.
This module never creates accounting entries or mutates the General Ledger.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation

BUDGET_STATES = {"Draft", "Pending Approval", "Approved", "Rejected", "Superseded"}
CHANGE_STATES = {"Draft", "Pending Approval", "Approved", "Rejected", "Cancelled"}


def amount(value, label, *, allow_negative=False):
    try:
        n = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be numeric.")
    if not n.is_finite() or (not allow_negative and n < 0):
        raise ValueError(f"{label} must be finite and {'signed' if allow_negative else 'non-negative'}.")
    return n


def iso_date(value, label):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{label} must use ISO YYYY-MM-DD format.")


def validate_budget_version(budget, prior_versions=()):
    required = ("project", "currency", "budget_version", "effective_from")
    missing = [k for k in required if not str(budget.get(k) if budget.get(k) is not None else "").strip()]
    if missing:
        raise ValueError("Budget version requires: " + ", ".join(missing))
    try:
        version = int(budget["budget_version"])
    except (TypeError, ValueError):
        raise ValueError("budget_version must be a positive integer.")
    if version < 1:
        raise ValueError("budget_version must be a positive integer.")
    iso_date(budget["effective_from"], "effective_from")
    approved = amount(budget.get("approved_amount"), "approved_amount")
    contingency = amount(budget.get("contingency_amount", 0), "contingency_amount")
    if contingency > approved:
        raise ValueError("Contingency cannot exceed the approved budget amount.")
    currency = str(budget["currency"])
    for old in prior_versions:
        if old.get("project") != budget["project"]:
            continue
        if old.get("currency") != currency:
            raise ValueError("Budget versions for a project must use the same currency; use a controlled currency conversion model instead.")
        if int(old.get("budget_version", 0)) == version:
            raise ValueError("Budget version number already exists for this project.")
    state = budget.get("approval_status", "Draft")
    if state not in BUDGET_STATES:
        raise ValueError("Unsupported budget approval status.")
    if state == "Approved" and (not budget.get("approved_by") or not budget.get("approval_reference")):
        raise ValueError("Approved budget requires approver and approval reference.")
    return {"valid": True, "project": budget["project"],
            "currency": currency, "budget_version": version, "approved_amount": approved,
            "contingency_amount": contingency, "approval_status": state,
            "immutable_when_approved": state == "Approved"}


def transition_budget(budget, target_status, *, actor_id, approval_reference=None, superseding_version=None):
    current = budget.get("approval_status", "Draft")
    allowed = {"Draft": {"Pending Approval"}, "Pending Approval": {"Approved", "Rejected"},
               "Rejected": {"Draft"}, "Approved": {"Superseded"}, "Superseded": set()}
    if target_status not in allowed.get(current, set()):
        raise ValueError(f"Invalid budget transition: {current} -> {target_status}")
    if target_status == "Approved":
        if not actor_id or not approval_reference:
            raise ValueError("Budget approval requires an authenticated approver and approval reference.")
        if str(actor_id) == str(budget.get("created_by")):
            raise ValueError("Budget creator cannot approve their own budget.")
    if target_status == "Superseded" and not superseding_version:
        raise ValueError("Superseding an approved budget requires the replacement budget version reference.")
    changed = deepcopy(budget)
    changed["approval_status"] = target_status
    if target_status == "Approved":
        changed["approved_by"] = actor_id
        changed["approval_reference"] = approval_reference
    if target_status == "Superseded":
        changed["superseded_by"] = superseding_version
    return changed


def validate_budget_allocation(budget, lines):
    if not isinstance(lines, list):
        raise ValueError("Budget lines must be a list.")
    total = Decimal("0"); seen = set()
    for line in lines:
        key = (str(line.get("wbs") or ""), str(line.get("cost_category") or ""), str(line.get("period") or ""))
        if key in seen:
            raise ValueError("Duplicate budget allocation line for WBS, cost category and period.")
        seen.add(key)
        if not key[1]:
            raise ValueError("Every budget line requires a cost category.")
        if line.get("period"):
            iso_date(line["period"], "budget line period")
        if line.get("currency") and line.get("currency") != budget.get("currency"):
            raise ValueError("Budget line currency must match the approved budget currency.")
        total += amount(line.get("budget_amount"), "budget_amount")
    authority = amount(budget.get("approved_amount"), "approved_amount")
    if total > authority:
        raise ValueError("Budget line allocations cannot exceed the approved budget authority.")
    return {"valid": True, "allocated_amount": total, "unallocated_amount": authority-total,
            "approved_authority": authority, "line_count": len(lines)}


def validate_budget_change(change):
    required = ("change_id", "project", "change_type", "currency", "justification")
    missing = [k for k in required if not str(change.get(k) or "").strip()]
    if missing:
        raise ValueError("Budget change requires: " + ", ".join(missing))
    if change["change_type"] not in {"Transfer", "Increase", "Decrease"}:
        raise ValueError("Unsupported budget change type.")
    value = amount(change.get("amount"), "amount")
    if value == 0:
        raise ValueError("Budget change amount must be greater than zero.")
    if change["change_type"] == "Transfer" and (not change.get("from_cost_category") or not change.get("to_cost_category")):
        raise ValueError("Budget transfer requires source and destination cost categories.")
    if change["change_type"] != "Transfer" and not change.get("reason_code"):
        raise ValueError("Budget increase/decrease requires a reason code.")
    if change.get("effective_date"):
        iso_date(change["effective_date"], "effective_date")
    state = change.get("status", "Draft")
    if state not in CHANGE_STATES:
        raise ValueError("Unsupported budget change status.")
    if state == "Approved" and (not change.get("approved_by") or not change.get("approval_reference")):
        raise ValueError("Approved budget change requires approver and approval reference.")
    authority_delta = Decimal("0")
    if state == "Approved" and change["change_type"] == "Increase":
        authority_delta = value
    elif state == "Approved" and change["change_type"] == "Decrease":
        authority_delta = -value
    return {"valid": True, "change_id": change["change_id"], "change_type": change["change_type"],
            "amount": value, "status": state, "authority_delta": authority_delta,
            "affects_budget_authority": authority_delta != 0,
            "reallocation_only": change["change_type"] == "Transfer"}


def transition_budget_change(change, target_status, *, actor_id, approval_reference=None):
    current = change.get("status", "Draft")
    allowed = {"Draft": {"Pending Approval", "Cancelled"}, "Pending Approval": {"Approved", "Rejected", "Cancelled"},
               "Rejected": {"Draft", "Cancelled"}, "Approved": set(), "Cancelled": set()}
    if target_status not in allowed.get(current, set()):
        raise ValueError(f"Invalid budget change transition: {current} -> {target_status}")
    if target_status == "Approved":
        if not actor_id or not approval_reference:
            raise ValueError("Approving a budget change requires an authenticated approver and approval reference.")
        if str(actor_id) == str(change.get("created_by")):
            raise ValueError("Budget change creator cannot approve their own request.")
    updated = deepcopy(change); updated["status"] = target_status
    if target_status == "Approved":
        updated["approved_by"] = actor_id; updated["approval_reference"] = approval_reference
    return updated


def validate_revenue_forecast(forecast):
    required = ("project", "period", "currency")
    missing = [k for k in required if not str(forecast.get(k) or "").strip()]
    if missing:
        raise ValueError("Revenue forecast requires: " + ", ".join(missing))
    iso_date(forecast["period"], "period")
    planned = amount(forecast.get("planned_revenue"), "planned_revenue")
    probability = amount(forecast.get("probability_percent", 100), "probability_percent")
    if probability > 100:
        raise ValueError("probability_percent cannot exceed 100.")
    weighted = planned * probability / Decimal("100")
    return {"valid": True, "planned_revenue": planned, "probability_percent": probability,
            "weighted_forecast_revenue": weighted, "recognised_revenue_source": "accounting_or_sales_source",
            "ledger_write_permitted": False}


def validate_posted_revenue(revenue, existing_source_keys=()):
    required = ("project", "source_doctype", "source_name", "source_line", "posting_reference", "posting_date", "currency")
    missing = [k for k in required if not str(revenue.get(k) or "").strip()]
    if missing:
        raise ValueError("Recognised revenue source requires: " + ", ".join(missing))
    if revenue.get("source_status") != "Posted" or revenue.get("is_cancelled") is True:
        raise ValueError("Only posted, non-cancelled source transactions may be imported as recognised revenue.")
    iso_date(revenue["posting_date"], "posting_date")
    value = amount(revenue.get("amount"), "amount")
    key = (revenue["source_doctype"], revenue["source_name"], revenue["source_line"])
    if key in set(tuple(x) for x in existing_source_keys):
        raise ValueError("Revenue source line has already been imported.")
    return {"valid": True, "source_key": key, "amount": value, "currency": revenue["currency"],
            "recognition_authority": "source_application", "ledger_write_permitted": False}


def aggregate_recognised_revenue(revenues, *, project, currency, as_at=None):
    cutoff = iso_date(as_at, "as_at") if as_at else None
    total = Decimal("0"); periods = {}; seen = set()
    for row in revenues:
        if row.get("project") != project:
            continue
        if row.get("source_status") != "Posted" or row.get("is_cancelled") is True:
            continue
        if row.get("currency") != currency:
            raise ValueError("Recognised revenue currency mismatch.")
        posted = iso_date(row.get("posting_date"), "posting_date")
        if cutoff and posted > cutoff:
            continue
        key = (row.get("source_doctype"), row.get("source_name"), row.get("source_line"))
        if key in seen:
            raise ValueError("Duplicate recognised revenue source line detected.")
        seen.add(key)
        value = amount(row.get("amount"), "amount")
        period = posted.strftime("%Y-%m")
        total += value; periods[period] = periods.get(period, Decimal("0")) + value
    return {"project": project, "currency": currency,
            "recognised_revenue": total, "by_period": periods,
            "source_of_recognised_revenue": "posted source-system transactions", "ledger_write_permitted": False}


def validate_posted_actual(actual, existing_source_keys=()):
    required = ("project", "source_doctype", "source_name", "source_line", "posting_reference", "posting_date", "currency", "cost_category")
    missing = [k for k in required if not str(actual.get(k) or "").strip()]
    if missing:
        raise ValueError("Actual cost source requires: " + ", ".join(missing))
    if actual.get("source_status") != "Posted":
        raise ValueError("Only posted source-system transactions may be imported as actual cost.")
    if actual.get("is_cancelled") is True:
        raise ValueError("Cancelled source transactions cannot be imported as actual cost.")
    iso_date(actual["posting_date"], "posting_date")
    value = amount(actual.get("amount"), "amount")
    key = (actual["source_doctype"], actual["source_name"], actual["source_line"])
    if key in set(tuple(x) for x in existing_source_keys):
        raise ValueError("Source transaction line has already been imported; duplicate actual cost is not permitted.")
    return {"valid": True, "source_key": key, "amount": value, "currency": actual["currency"],
            "project": actual["project"], "posting_authority": "source_application",
            "ledger_write_permitted": False, "read_only_mirror": True}


def aggregate_actual_costs(actuals, *, project, currency, as_at=None):
    cutoff = iso_date(as_at, "as_at") if as_at else None
    total = Decimal("0"); categories = {}; periods = {}; seen = set()
    for row in actuals:
        if row.get("project") != project:
            continue
        if row.get("source_status") != "Posted" or row.get("is_cancelled") is True:
            continue
        if row.get("currency") != currency:
            raise ValueError("Actual cost currency mismatch; convert through an approved accounting exchange-rate source before aggregation.")
        posted = iso_date(row.get("posting_date"), "posting_date")
        if cutoff and posted > cutoff:
            continue
        key = (row.get("source_doctype"), row.get("source_name"), row.get("source_line"))
        if key in seen:
            raise ValueError("Duplicate posted source line detected in actual cost read model.")
        seen.add(key)
        value = amount(row.get("amount"), "amount")
        category = str(row.get("cost_category") or "Unclassified")
        period = posted.strftime("%Y-%m")
        total += value; categories[category] = categories.get(category, Decimal("0")) + value
        periods[period] = periods.get(period, Decimal("0")) + value
    return {"project": project, "currency": currency, "as_at": cutoff.isoformat() if cutoff else None,
            "actual_cost": total, "by_category": categories, "by_period": periods,
            "source_of_actuals": "posted source-system transactions", "ledger_write_permitted": False}


def project_financial_forecast(*, approved_budget, actual_cost, open_commitments, estimate_to_complete,
                               approved_budget_changes=0, pending_budget_changes=0, recognised_revenue=0,
                               forecast_revenue=0, currency=None):
    budget = amount(approved_budget, "approved_budget")
    actual = amount(actual_cost, "actual_cost")
    commitments = amount(open_commitments, "open_commitments")
    etc = amount(estimate_to_complete, "estimate_to_complete")
    approved_changes = amount(approved_budget_changes, "approved_budget_changes", allow_negative=True)
    pending_changes = amount(pending_budget_changes, "pending_budget_changes", allow_negative=True)
    recognised = amount(recognised_revenue, "recognised_revenue")
    revenue_forecast = amount(forecast_revenue, "forecast_revenue")
    revised_budget = budget + approved_changes
    if revised_budget < 0:
        raise ValueError("Approved budget decreases cannot reduce budget authority below zero.")
    eac = actual + commitments + etc
    remaining_authority = revised_budget - actual - commitments
    return {"currency": currency, "original_budget": budget, "approved_budget_changes": approved_changes,
            "pending_budget_changes_excluded": pending_changes, "revised_budget": revised_budget,
            "actual_cost": actual, "open_commitments": commitments, "estimate_to_complete": etc,
            "estimate_at_completion": eac, "forecast_variance": revised_budget-eac,
            "forecast_overrun": max(Decimal("0"), eac-revised_budget),
            "remaining_budget_after_actual_and_commitments": remaining_authority,
            "recognised_revenue": recognised, "forecast_revenue": revenue_forecast,
            "forecast_project_margin": revenue_forecast-eac,
            "cost_to_revenue_ratio": eac/revenue_forecast if revenue_forecast else None,
            "pending_changes_affect_authority": False, "ledger_write_permitted": False}


def category_cost_control(budget_lines, actuals, commitments, estimates, *, currency=None):
    """Return category-level budget/actual/commitment/ETC variance read model."""
    categories = set()
    for rows in (budget_lines, actuals, commitments, estimates):
        currencies = {str(r.get("currency")) for r in rows if r.get("currency")}
        if currency and any(c != currency for c in currencies):
            raise ValueError("Cost category control currency mismatch.")
        if not currency and len(currencies) > 1:
            raise ValueError("Cost category control cannot aggregate mixed currencies.")
        categories.update(str(r.get("cost_category") or "Unclassified") for r in rows)
    output = []
    for category in sorted(categories):
        def total(rows, key):
            return sum((amount(r.get(key), key) for r in rows if str(r.get("cost_category") or "Unclassified") == category), Decimal("0"))
        budget = total(budget_lines, "budget_amount")
        actual = total(actuals, "amount")
        committed = total(commitments, "open_amount")
        etc = total(estimates, "estimate_to_complete")
        eac = actual+committed+etc
        output.append({"cost_category": category, "budget": budget, "actual": actual,
                       "open_commitments": committed, "estimate_to_complete": etc,
                       "estimate_at_completion": eac, "variance_at_completion": budget-eac})
    return output


def portfolio_financial_rollup(project_positions):
    """Aggregate project positions by currency; never add unlike currencies."""
    groups = {}
    for row in project_positions:
        currency = str(row.get("currency") or "")
        if not currency:
            raise ValueError("Every project financial position requires currency.")
        bucket = groups.setdefault(currency, {"project_count": 0, "approved_budget": Decimal("0"),
            "actual_cost": Decimal("0"), "open_commitments": Decimal("0"),
            "estimate_at_completion": Decimal("0"), "recognised_revenue": Decimal("0")})
        bucket["project_count"] += 1
        for key in ("approved_budget", "actual_cost", "open_commitments", "estimate_at_completion", "recognised_revenue"):
            bucket[key] += amount(row.get(key, 0), key)
    for currency, row in groups.items():
        row["forecast_variance"] = row["approved_budget"] - row["estimate_at_completion"]
        row["forecast_margin"] = row["recognised_revenue"] - row["estimate_at_completion"]
    return {"currencies": groups, "currency_conversion_performed": False,
            "ledger_write_permitted": False}


def calculate_revenue_recognition(*, project, performance_obligation, currency,
                                   transaction_price, method, period_end,
                                   cumulative_actual_cost=0, forecast_total_cost=0,
                                   cumulative_progress_percent=None, cumulative_output_units=None,
                                   total_output_units=None, achieved_milestone_value=None,
                                   prior_cumulative_revenue=0, prior_cumulative_cost=0,
                                   current_period_cost=0, recognition_over_time=True, control_transfer_confirmed=False,
                                   variable_consideration_constrained=True):
    """Calculate a reviewable project revenue-recognition proposal; never post a ledger.

    Cost-to-cost and output methods are progress measures, not automatic conclusions
    that a performance obligation qualifies for over-time recognition. That conclusion
    is supplied by the approved contract/accounting policy.
    """
    required = {"project": project, "performance_obligation": performance_obligation,
                "currency": currency, "period_end": period_end}
    missing = [k for k, v in required.items() if not str(v or "").strip()]
    if missing:
        raise ValueError("Revenue recognition requires: " + ", ".join(missing))
    iso_date(period_end, "period_end")
    price = amount(transaction_price, "transaction_price")
    actual_cost = amount(cumulative_actual_cost, "cumulative_actual_cost")
    total_cost = amount(forecast_total_cost, "forecast_total_cost")
    prior_revenue = amount(prior_cumulative_revenue, "prior_cumulative_revenue")
    prior_cost = amount(prior_cumulative_cost, "prior_cumulative_cost")
    period_cost = amount(current_period_cost, "current_period_cost")
    if not variable_consideration_constrained:
        raise ValueError("Unconstrained variable consideration cannot be included in the recognition proposal.")
    method = str(method or "").strip().lower().replace("-", "_").replace(" ", "_")
    if method not in {"cost_to_cost", "output", "milestone", "time_elapsed", "point_in_time"}:
        raise ValueError("Unsupported revenue recognition method.")
    if method == "point_in_time":
        if recognition_over_time:
            raise ValueError("Point-in-time method requires recognition_over_time=False.")
        if not control_transfer_confirmed:
            raise ValueError("Point-in-time recognition requires documented transfer-of-control confirmation.")
        progress = Decimal("1")
    else:
        if not recognition_over_time:
            raise ValueError("This progress method requires an approved over-time recognition conclusion.")
        if method == "cost_to_cost":
            if total_cost <= 0:
                raise ValueError("Cost-to-cost requires a positive forecast total cost.")
            progress = actual_cost / total_cost
        elif method == "output":
            if cumulative_output_units is None or total_output_units is None:
                raise ValueError("Output method requires cumulative_output_units and total_output_units.")
            done = amount(cumulative_output_units, "cumulative_output_units")
            total = amount(total_output_units, "total_output_units")
            if total <= 0 or done > total:
                raise ValueError("Output method requires positive total units and completed units not exceeding total units.")
            progress = done / total
        elif method == "milestone":
            if achieved_milestone_value is None:
                raise ValueError("Milestone method requires achieved_milestone_value.")
            achieved = amount(achieved_milestone_value, "achieved_milestone_value")
            if achieved > price:
                raise ValueError("Achieved milestone value cannot exceed the transaction price.")
            progress = achieved / price if price else Decimal("0")
        else:  # time elapsed
            if cumulative_progress_percent is None:
                raise ValueError("Time-elapsed method requires cumulative_progress_percent.")
            elapsed = amount(cumulative_progress_percent, "cumulative_progress_percent")
            if elapsed > 100:
                raise ValueError("cumulative_progress_percent cannot exceed 100.")
            progress = elapsed / Decimal("100")
    progress = min(Decimal("1"), max(Decimal("0"), progress))
    if prior_revenue > price:
        raise ValueError("Prior cumulative revenue cannot exceed the allocated transaction price.")
    cumulative_revenue = price * progress
    if cumulative_revenue < prior_revenue:
        # Estimate changes can cause a downward cumulative catch-up; expose it explicitly.
        current_revenue = cumulative_revenue - prior_revenue
    else:
        current_revenue = cumulative_revenue - prior_revenue
    cumulative_cost = actual_cost if method == "cost_to_cost" else prior_cost + period_cost
    current_cost = cumulative_cost - prior_cost
    cumulative_profit = cumulative_revenue - cumulative_cost
    current_profit = current_revenue - current_cost
    forecast_cost = total_cost if total_cost else cumulative_cost
    forecast_profit = price - forecast_cost
    return {"valid": True, "project": project,
            "performance_obligation": performance_obligation, "currency": currency,
            "period_end": period_end, "method": method,
            "progress_percent": progress * Decimal("100"),
            "transaction_price": price, "cumulative_revenue": cumulative_revenue,
            "prior_cumulative_revenue": prior_revenue, "current_period_revenue": current_revenue,
            "cumulative_cost": cumulative_cost, "current_period_cost": current_cost,
            "cumulative_profit": cumulative_profit, "current_period_profit": current_profit,
            "forecast_total_cost": forecast_cost, "forecast_total_profit": forecast_profit,
            "forecast_margin_percent": (forecast_profit / price * Decimal("100")) if price else None,
            "potential_onerous_contract_loss": forecast_profit < 0,
            "requires_review": True, "approval_status": "Pending Review",
            "ledger_write_permitted": False,
            "recognition_basis": "approved contract policy and applicable accounting standard"}


def calculate_earned_value(*, planned_value, earned_value, actual_cost, budget_at_completion):
    """Cost/schedule performance indicators using a consistent project currency."""
    pv = amount(planned_value, "planned_value")
    ev = amount(earned_value, "earned_value")
    ac = amount(actual_cost, "actual_cost")
    bac = amount(budget_at_completion, "budget_at_completion")
    if ev > bac or pv > bac:
        raise ValueError("Planned value and earned value cannot exceed budget at completion.")
    cv = ev - ac
    sv = ev - pv
    cpi = ev / ac if ac else None
    spi = ev / pv if pv else None
    eac = bac / cpi if cpi else None
    etc = eac - ac if eac is not None else None
    vac = bac - eac if eac is not None else None
    return {"planned_value": pv, "earned_value": ev, "actual_cost": ac,
            "cost_variance": cv, "schedule_variance": sv,
            "cost_performance_index": cpi, "schedule_performance_index": spi,
            "estimate_at_completion": eac, "estimate_to_complete": etc,
            "variance_at_completion": vac, "currency_safe": True}


def validate_performance_obligation(obligation):
    required = ("project", "contract_reference", "obligation_code", "description",
                "currency", "recognition_method", "accounting_conclusion_reference")
    missing = [k for k in required if not str(obligation.get(k) or "").strip()]
    if missing:
        raise ValueError("Performance obligation requires: " + ", ".join(missing))
    price = amount(obligation.get("allocated_transaction_price"), "allocated_transaction_price")
    if price <= 0:
        raise ValueError("Allocated transaction price must be greater than zero.")
    method = str(obligation["recognition_method"]).strip().lower().replace("-", "_").replace(" ", "_")
    if method not in {"cost_to_cost", "output", "milestone", "time_elapsed", "point_in_time"}:
        raise ValueError("Unsupported performance obligation recognition method.")
    over_time = bool(obligation.get("recognition_over_time", True))
    if method == "point_in_time" and over_time:
        raise ValueError("Point-in-time method cannot be marked as an over-time obligation.")
    if method != "point_in_time" and not over_time:
        raise ValueError("Progress-based method requires an approved over-time conclusion.")
    status = obligation.get("status", "Draft")
    if status not in {"Draft", "Pending Approval", "Approved", "Suspended", "Completed"}:
        raise ValueError("Unsupported performance obligation status.")
    if status == "Approved" and (not obligation.get("approved_by") or not obligation.get("approval_reference")):
        raise ValueError("Approved performance obligation requires approver and approval reference.")
    return {"valid": True, "allocated_transaction_price": price, "recognition_method": method,
            "recognition_over_time": over_time, "status": status,
            "immutable_when_approved": status in {"Approved", "Suspended", "Completed"}}


def transition_performance_obligation(obligation, target_status, *, actor_id, approval_reference=None):
    current = obligation.get("status", "Draft")
    allowed = {"Draft": {"Pending Approval"}, "Pending Approval": {"Approved", "Draft"},
               "Approved": {"Suspended", "Completed"}, "Suspended": {"Approved", "Completed"},
               "Completed": set()}
    if target_status not in allowed.get(current, set()):
        raise ValueError(f"Invalid performance obligation transition: {current} -> {target_status}")
    if target_status == "Approved":
        if not actor_id or not approval_reference:
            raise ValueError("Performance obligation approval requires an authenticated approver and approval reference.")
        if str(actor_id) == str(obligation.get("created_by")):
            raise ValueError("Performance obligation creator cannot approve their own accounting policy.")
    changed = deepcopy(obligation); changed["status"] = target_status
    if target_status == "Approved":
        changed["approved_by"] = actor_id; changed["approval_reference"] = approval_reference
    return changed
