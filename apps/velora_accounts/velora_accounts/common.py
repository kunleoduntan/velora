"""Shared helpers for the financial engine: exact money, dates, account lookups, defaults, roles."""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import select

from velora import db, throw
from velora.db.tables import get_table
from velora.permissions import get_session
from velora.settings import get_setting, set_setting

CENT = Decimal("0.01")
CASH_TYPES = ("Bank", "Cash")
PARTY_RULES = {"Receivable": ("Customer",), "Payable": ("Supplier", "Employee")}
MANAGER_ROLES = ("System Manager", "Accounts Manager")


def D(v) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        throw(f"{v!r} is not a number")


def money(v, what: str = "Amount") -> Decimal:
    """Exact 2-decimal money. More precision than a kobo/cent is REFUSED, never silently rounded."""
    d = D(v)
    q = d.quantize(CENT, rounding=ROUND_HALF_UP)
    if q != d:
        throw(f"{what} {d} has more than 2 decimal places")
    return q


def round_money(v) -> Decimal:
    return D(v).quantize(CENT, rounding=ROUND_HALF_UP)


def to_date(v, what: str = "Date") -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        throw(f"{what} {v!r} is not a valid date")


def has_role(*roles: str) -> bool:
    s = get_session()
    return s.user == "Administrator" or any(r in s.roles for r in roles)


def accounts_info(names) -> dict[str, dict]:
    """Account facts for the engine (internal lookup: no permission check - the caller's document permission is the gate)."""
    names = sorted({n for n in names if n})
    if not names:
        return {}
    t = get_table("Account")
    with db.transaction() as conn:
        rows = conn.execute(select(t.c.name, t.c.is_group, t.c.disabled, t.c.account_type, t.c.root_type).where(t.c.name.in_(names))).mappings().all()
    return {r["name"]: dict(r) for r in rows}


def is_cash(info: dict) -> bool:
    return info.get("account_type") in CASH_TYPES


def check_postable(acc: dict | None, name: str, where: str = "") -> dict:
    pre = f"{where}: " if where else ""
    if acc is None:
        throw(f"{pre}account {name!r} does not exist")
    if acc.get("is_group"):
        throw(f"{pre}{name} is a group account; post to one of its sub-accounts")
    if acc.get("disabled"):
        throw(f"{pre}{name} is disabled")
    return acc


# ---- company-level settings -------------------------------------------------------------------
DEFAULT_KINDS = {"receivable": "Receivable", "payable": "Payable", "wht_payable": "Tax", "wht_receivable": "Tax", "gateway_fees": None, "prepayments": None, "discount_allowed": None, "discount_received": None, "sales_income": None, "retained_earnings": "Retained Earnings"}


def get_default(kind: str, required: bool = True) -> str | None:
    name = (get_setting("accounts.defaults", {}) or {}).get(kind)
    if required and not name:
        throw(f"No default {kind.replace('_', ' ')} account is set. Set one with velora_accounts.common.set_default({kind!r}, '<account>')")
    return name


def set_default(kind: str, account: str) -> None:
    if kind not in DEFAULT_KINDS:
        throw(f"Unknown default {kind!r}; use one of {', '.join(DEFAULT_KINDS)}")
    if not has_role(*MANAGER_ROLES):
        throw("Only an Accounts Manager can change default accounts")
    info = accounts_info([account]).get(account)
    check_postable(info, account)
    need = DEFAULT_KINDS[kind]
    if need and info["account_type"] != need:
        throw(f"{account} must be a {need} account to be the default {kind.replace('_', ' ')} account")
    cur = dict(get_setting("accounts.defaults", {}) or {})
    cur[kind] = account
    set_setting("accounts.defaults", cur)


def get_lock_date() -> date | None:
    v = get_setting("accounts.lock_date")
    return date.fromisoformat(v) if v else None


def set_lock_date(d) -> None:
    """Books are locked up to and including this date: NOTHING may be posted or reversed on or before it, for anyone."""
    if not has_role(*MANAGER_ROLES):
        throw("Only an Accounts Manager can set the books lock date")
    set_setting("accounts.lock_date", to_date(d, "Lock date").isoformat() if d else None)


# ---- party master ------------------------------------------------------------------------------------
MASTERS = {"Customer": "Customer", "Supplier": "Supplier"}          # Employee has no master here (HR owns it)


def strict_parties() -> bool:
    """On (default): a Customer/Supplier must exist in the master before anything can be posted to them - a typo can never create a ghost account.
    Off: free-text parties are accepted (useful while importing opening balances from a legacy system)."""
    v = get_setting("accounts.strict_parties")
    return True if v is None else bool(v)


def set_strict_parties(on: bool) -> None:
    if not has_role(*MANAGER_ROLES):
        throw("Only an Accounts Manager can change this setting")
    set_setting("accounts.strict_parties", bool(on))


def require_parties(pairs) -> None:
    """pairs: iterable of (party_type, party). Raises if a master party does not exist (strict mode)."""
    if not strict_parties():
        return
    by_type: dict[str, set] = {}
    for pt, p in pairs:
        if pt in MASTERS and p:
            by_type.setdefault(pt, set()).add(p)
    for pt, names in by_type.items():
        t = get_table(pt)
        with db.transaction() as conn:
            found = {r[0] for r in conn.execute(select(t.c.name).where(t.c.name.in_(sorted(names))))}
        missing = sorted(names - found)
        if missing:
            throw(f"{pt} {missing[0]!r} does not exist. Create the {pt.lower()} first{' (' + str(len(missing)) + ' missing)' if len(missing) > 1 else ''}.")
