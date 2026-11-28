"""Investment routes: portfolio view, accruals, roll-over. Installed by velora_erp.api_routes."""
from __future__ import annotations

from datetime import date

from fastapi import Body, FastAPI, Request

from velora import get_doc, new_doc, throw
from velora.meta.registry import registry
from velora.permissions import check_permission

from . import calculations as calc
from . import jobs, posting
from .portfolio import portfolio


def _date(value, label="date"):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        throw(f"The {label} must look like 2026-12-31.")


def rollover(name: str, capitalise: bool = False, rate: float | None = None, tenor_days: int | None = None):
    """Draft the next placement from a matured investment: same terms, starting on the maturity date. The new draft is not submitted."""
    old = get_doc("Investment", name, ignore_permissions=True)
    if old.status != "Matured":
        throw("Only a matured investment can be rolled over. Record the maturity first.")
    matured = [t for t in __import__("velora").get_list("Investment Transaction", filters={"investment": name, "transaction_type": "Maturity", "docstatus": 1, "status": "Posted"}, fields=["transaction_date", "wht_amount", "d_received"], limit=1, ignore_permissions=True)]
    start = matured[0]["transaction_date"] if matured else old.maturity_date
    net_income = calc.money(calc.D(old.income_received) - calc.D(old.wht_suffered))
    principal = calc.money(calc.D(old.principal) + (net_income if capitalise else 0))
    new = new_doc("Investment", investment_name=f"{old.investment_name} (rolled over)", investment_class=old.investment_class, counterparty=old.counterparty, counterparty_type=old.counterparty_type,
                  reference_no=None, currency=old.currency, exchange_rate=old.exchange_rate, measurement=old.measurement, start_date=start, tenor_days=tenor_days or old.tenor_days,
                  principal=principal, interest_rate=rate if rate is not None else old.interest_rate, interest_method="Simple Interest" if old.interest_method == "Discount (T-Bill)" else old.interest_method,
                  day_count=old.day_count, payment_mode=old.payment_mode, payment_frequency=old.payment_frequency, management_fee_percent=old.management_fee_percent, wht_applicable=old.wht_applicable,
                  wht_rate=old.wht_rate, investment_account=old.investment_account, bank_account=old.bank_account, income_account=old.income_account, accrued_income_account=old.accrued_income_account,
                  cost_centre=old.cost_centre, rollover_instruction=old.rollover_instruction, description=f"Rolled over from {old.name}.")
    new.insert()
    return {"name": new.name}


def install_investment_routes(app: FastAPI, run):
    @app.get("/api/investments/portfolio")
    def portfolio_route(request: Request, as_of: str = ""):
        def fn():
            check_permission(registry.get("Investment"), "read")
            return portfolio(_date(as_of, "as-of date"))
        return run(request, fn)

    @app.post("/api/investments/accrue")
    def accrue_all_route(request: Request, body: dict = Body(default={})):
        def fn():
            check_permission(registry.get("Investment Transaction"), "create")
            return jobs.accrue_all(_date(body.get("as_of"), "as-of date"))
        return run(request, fn)

    @app.post("/api/investments/{name}/accrue")
    def accrue_one_route(name: str, request: Request, body: dict = Body(default={})):
        def fn():
            check_permission(registry.get("Investment Transaction"), "create")
            tx = jobs.accrue(name, _date(body.get("as_of"), "as-of date") or date.today())
            return {"transaction": tx, "message": "Nothing new to accrue." if tx is None else f"Income recognised in {tx}."}
        return run(request, fn)

    @app.post("/api/investments/{name}/rollover")
    def rollover_route(name: str, request: Request, body: dict = Body(default={})):
        def fn():
            check_permission(registry.get("Investment"), "create")
            return rollover(name, bool(body.get("capitalise")), body.get("rate"), body.get("tenor_days"))
        return run(request, fn)
