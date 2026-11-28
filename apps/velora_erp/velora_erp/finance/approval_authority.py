"""Configurable authority for the few actions that are not document approvals.

Approving a document (voucher, invoice, payroll run, budget, ...) is a GUI-managed workflow: who approves differs per
company, so no approval rule lives in code. What remains here are separate powers that no workflow step covers:
overriding a budget block, reversing a posted financial document, approving a scheduled report, the reporting-case
roles and approving an HR policy version. The company sets who holds each in Finance Settings > Approvals ("Other powers");
DEFAULTS apply until it does. The built-in `Administrator` identity always keeps authority, so a bad configuration can
never lock a company out.
"""
from __future__ import annotations

SETTING_KEY = "finance.approval_authority"

# Nobody is restricted by code. A company that wants a power held by certain roles types them in Finance Settings > Approvals
# (empty = anyone whose role permissions allow the action). Approving a DOCUMENT is never decided here: that is a GUI workflow.
DEFAULTS: dict[str, tuple[str, ...]] = {
    "budget.override": (),
    "hr_policy.approve": (),
}

LABELS: dict[str, str] = {
    "budget.override": "Override a budget block",
    "hr_policy.approve": "Approve an HR policy version",
}


class ApprovalAuthorityError(ValueError):
    pass


def _legacy() -> dict:
    try:
        from velora.settings import get_setting
        value = get_setting(SETTING_KEY, {}) or {}
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001 - no settings table yet: defaults apply
        return {}


def _split(text) -> list[str]:
    return [r.strip() for r in str(text or "").split(",") if r.strip()]


def _configured() -> dict:
    """Roles per action: the Finance Settings table first, then the older settings key (kept for companies that used it)."""
    out = {k: v for k, v in _legacy().items() if isinstance(v, (list, tuple))}
    try:
        from sqlalchemy import select
        from velora import db
        from velora.db.tables import get_table
        table = get_table("Authority Policy Row")
        with db.transaction() as c:
            for action, roles in c.execute(select(table.c.action, table.c.roles).where(table.c.parenttype == "Finance Settings")).all():
                if _split(roles):
                    out[action] = _split(roles)
    except Exception:  # noqa: BLE001 - settings not created yet: defaults apply
        pass
    return out


def effective_roles(action: str) -> list[str]:
    return list(roles_for(action))


def sync_rows(doc) -> None:
    """Finance Settings lists every power once, in a fixed order. New rows start with the roles currently in force."""
    have = {}
    for row in doc.authority_policy or []:
        if row.action in DEFAULTS and row.action not in have:
            have[row.action] = row
    doc.authority_policy = []
    for action in DEFAULTS:
        row = have.get(action)
        roles = _split(row.roles) if row else effective_roles(action)          # a row the company blanked stays blank (= anyone)
        doc.append("authority_policy", {"action": action, "power": LABELS[action], "roles": ", ".join(roles)})
    doc._link_children()


def roles_for(action: str) -> tuple[str, ...]:
    if action not in DEFAULTS:
        raise ApprovalAuthorityError(f"Unknown approval action: {action}")
    configured = _configured().get(action)
    if isinstance(configured, (list, tuple)):
        roles = tuple(str(r).strip() for r in configured if str(r).strip())
        if roles:
            return roles
    return DEFAULTS[action]


def is_authorised(action: str, *, user: str = "", roles=()) -> bool:
    held = roles_for(action)
    return not held or user == "Administrator" or bool(set(held) & set(roles or ()))     # no roles named = unrestricted


def describe(action: str) -> str:
    return " or ".join(roles_for(action)) or "anyone with permission"


def _write_rows(action: str, roles: list[str]) -> None:
    from sqlalchemy import update
    from velora import db
    from velora.db.tables import get_table
    try:
        table = get_table("Authority Policy Row")
    except Exception:                                      # the app's doctypes are not loaded (a bare framework site)
        table = None
    with db.transaction() as c:
        done = table is not None and c.execute(update(table).where(table.c.parenttype == "Finance Settings", table.c.action == action).values(roles=", ".join(roles))).rowcount
    if not done:                                           # Finance Settings has not listed this power yet: keep it in the settings store
        from velora.settings import get_setting, set_setting
        current = dict(get_setting(SETTING_KEY, {}) or {})
        current[action] = list(roles)
        set_setting(SETTING_KEY, current)


def _require_admin():
    from velora.permissions import PermissionDenied, get_session
    session = get_session()
    if session.user != "Administrator" and "System Manager" not in set(session.roles):
        raise PermissionDenied("Only a System Manager can change approval authority.")


def set_authority(action: str, roles: list[str]) -> tuple[str, ...]:
    """Configure which roles hold `action` (the same table as Finance Settings > Approvals). Only a System Manager may change it."""
    _require_admin()
    if action not in DEFAULTS:
        raise ApprovalAuthorityError(f"Unknown approval action: {action}")
    clean = [str(r).strip() for r in roles or [] if str(r).strip()]
    if not clean:
        raise ApprovalAuthorityError("Name at least one role; use reset_authority to return to the defaults.")
    _write_rows(action, clean)
    return tuple(clean)


def reset_authority(action: str) -> None:
    _require_admin()
    if action not in DEFAULTS:
        raise ApprovalAuthorityError(f"Unknown approval action: {action}")
    _write_rows(action, list(DEFAULTS[action]))
    from velora.settings import get_setting, set_setting
    legacy = dict(get_setting(SETTING_KEY, {}) or {})
    if legacy.pop(action, None) is not None:
        set_setting(SETTING_KEY, legacy)
