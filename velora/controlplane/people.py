"""People and access for one company, in one step.

Add a person: type the email and name, tick what they do (an access profile such as "Accountant", or roles), press Add. The person is
created if new (active, with a one-time temporary password shown once), or simply given access if they already have a Velora sign-in.
Roles are checked against the roles this company actually uses, so a typo cannot quietly give someone no access; the closest names are
suggested instead.

Who may do it: a platform administrator, or a System Manager of the company being changed (only that company, and never platform rights).
A company can never be left without a System Manager."""
from __future__ import annotations

import difflib

from sqlalchemy import and_, select

from . import models as m
from .identity import EMAIL_RE
from ..exceptions import PermissionDenied, ValidationError


def _company_db_roles(plane, company: dict) -> dict[str, list[str]]:
    from .. import site as site_mod
    from ..db.system import company_user_role
    site = plane.router.site_for(company)
    with site_mod.use(site):
        company_user_role.create(site.engine, checkfirst=True)
        with site.engine.connect() as c:
            return {r[0]: list(r[1] or []) for r in c.execute(select(company_user_role.c.user_email, company_user_role.c.roles))}


def access_profiles() -> list[dict]:
    """Named bundles of roles that apps offer (hook `access_profiles`: a dict name -> {"roles": [...], "description": ...})."""
    from importlib import import_module
    from ..meta.registry import registry
    out = {}
    for app_name in registry.apps:
        try:
            prof = getattr(import_module(f"{app_name}.hooks"), "access_profiles", None)
        except ModuleNotFoundError:
            continue
        for name, spec in (prof or {}).items():
            out[name] = {"name": name, "roles": list(spec.get("roles", [])), "description": spec.get("description", ""), "app": app_name}
    out.setdefault("Administrator of this company", {"name": "Administrator of this company", "roles": ["System Manager"],
                                                       "description": "Sets up the company: people, permissions, workflows and settings.", "app": "velora"})
    return sorted(out.values(), key=lambda p: p["name"])


def known_roles() -> list[dict]:
    """Every role this company can give, with the documents each one opens (for the tick boxes)."""
    from ..meta.registry import registry
    from .. import db
    from .role_admin import RoleAdministration
    from ..permissions import get_session
    uses: dict[str, set] = {"System Manager": set()}
    for meta in registry.all():
        if getattr(meta, "istable", False):
            continue
        for p in meta.permissions:
            role = getattr(p, "role", None)
            if role and role not in ("All", "Guest") and getattr(p, "read", False):
                uses.setdefault(role, set()).add(meta.module or meta.app)
    try:
        for r in RoleAdministration(db.get_engine()).list_roles(get_session()):
            uses.setdefault(r["name"], set())
    except Exception:
        pass
    return [{"name": n, "areas": sorted(a for a in uses[n] if a)} for n in sorted(uses)]


class People:
    def __init__(self, plane):
        self.plane = plane

    # ---- who may ---------------------------------------------------------------------------------
    def _check(self, actor_email: str, actor_roles, company_id: str):
        with self.plane.engine.connect() as c:
            row = c.execute(select(m.user.c.is_platform_admin).where(m.user.c.email == (actor_email or "").lower())).first()
        if row and row[0]:
            return
        from ..company import current_company
        here = current_company()
        if "System Manager" in set(actor_roles or ()) and here is not None and here.id == company_id:
            return
        raise PermissionDenied("Only a System Manager of this company (or a platform administrator) can manage its people.")

    def _company(self, company_id: str) -> dict:
        co = self.plane.registry.get_company(company_id)
        if not co or co.get("status", "active") != "active":
            raise ValidationError("This company is not active.")
        return co

    def _validate_roles(self, roles) -> list[str]:
        if not isinstance(roles, list) or not roles:
            raise ValidationError("Choose at least one role or access profile.",
                                  advice={"hint": "Tick what this person does (for example Accountant). You can change it at any time.", "field": "roles"})
        known = {r["name"] for r in known_roles()}
        clean = sorted({str(r).strip() for r in roles if str(r).strip()})
        unknown = [r for r in clean if r not in known]
        if unknown:
            close = {u: difflib.get_close_matches(u, sorted(known), n=2, cutoff=0.6) for u in unknown}
            said = "; ".join(f"{u!r}" + (f" (did you mean {' or '.join(repr(x) for x in close[u])}?)" if close[u] else "") for u in unknown)
            raise ValidationError(f"This company has no role {said}.",
                                  advice={"hint": "Pick roles from the list. To make a new kind of role, add it first in Role Permissions.",
                                          "actions": [{"label": "Role Permissions", "href": "#/settings/permissions"}], "field": "roles"})
        return clean

    def _guard_last_admin(self, company: dict, email: str, new_roles: list[str] | None):
        if new_roles is not None and "System Manager" in new_roles:
            return
        holders = [e for e, roles in _company_db_roles(self.plane, company).items() if "System Manager" in roles]
        if holders == [email]:
            raise ValidationError("This is the company's only System Manager.",
                                  advice={"hint": "Give another person the System Manager role first, then change or remove this one."})

    # ---- read ------------------------------------------------------------------------------------
    def list(self, actor_email, actor_roles, company_id: str) -> list[dict]:
        self._check(actor_email, actor_roles, company_id)
        company = self._company(company_id)
        roles = _company_db_roles(self.plane, company)
        with self.plane.engine.connect() as c:
            rows = c.execute(select(m.user.c.email, m.user.c.full_name, m.user.c.is_active, m.user.c.last_login, m.user_company.c.roles)
                             .join(m.user_company, m.user_company.c.user_id == m.user.c.id)
                             .where(m.user_company.c.company_id == company_id).order_by(m.user.c.full_name)).all()
        return [{"email": e, "full_name": n, "is_active": bool(a), "last_login": ll, "roles": roles.get(e, list(legacy or []))} for e, n, a, ll, legacy in rows]

    # ---- change ----------------------------------------------------------------------------------
    def add(self, actor_email, actor_roles, company_id: str, *, email: str, full_name: str = "", roles=None) -> dict:
        self._check(actor_email, actor_roles, company_id)
        self._company(company_id)
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise ValidationError("Enter a valid email address.", advice={"hint": "Use the person's work email, for example ada@yourcompany.com.", "field": "email"})
        clean = self._validate_roles(roles)
        with self.plane.engine.connect() as c:
            existing = c.execute(select(m.user.c.id, m.user.c.is_active, m.user.c.full_name).where(m.user.c.email == email)).first()
            already = existing is not None and c.execute(select(m.user_company.c.user_id).where(and_(m.user_company.c.user_id == existing[0], m.user_company.c.company_id == company_id))).first()
        if already:
            raise ValidationError(f"{email} already works in this company.", advice={"hint": "Open the person in the list and change their roles instead."})
        temporary = None
        if existing is None:
            self.plane.identity.create_user(email, (full_name or email.split("@")[0]).strip()[:200], __import__("secrets").token_urlsafe(32))
            user_id = self.plane.identity.get_user(email)["id"]
            temporary = self.plane.passwords.issue_temporary(_SystemActor(actor_email), user_id).get("temporary_password") if hasattr(self.plane, "passwords") else None
        elif not existing[1]:
            raise ValidationError(f"{email} has a Velora sign-in that is suspended.", advice={"hint": "Ask a platform administrator to reactivate it, then add the person again."})
        self.plane.identity.grant(email, company_id, clean, actor=actor_email)
        self.plane.audit("people.added", actor=actor_email, subject=email, detail={"company": company_id, "roles": clean, "new": existing is None})
        return {"email": email, "full_name": full_name or (existing[2] if existing else email.split("@")[0]), "roles": clean, "new_user": existing is None,
                "temporary_password": temporary}

    def set_roles(self, actor_email, actor_roles, company_id: str, email: str, roles) -> dict:
        self._check(actor_email, actor_roles, company_id)
        company = self._company(company_id)
        email = (email or "").strip().lower()
        clean = self._validate_roles(roles)
        self._guard_last_admin(company, email, clean)
        self.plane.identity.grant(email, company_id, clean, actor=actor_email)
        return {"email": email, "roles": clean}

    def remove(self, actor_email, actor_roles, company_id: str, email: str) -> bool:
        self._check(actor_email, actor_roles, company_id)
        company = self._company(company_id)
        email = (email or "").strip().lower()
        self._guard_last_admin(company, email, None)
        self.plane.identity.revoke(email, company_id, actor=actor_email)
        return True


class _SystemActor:
    """Lets People issue the first temporary password of a person it has just created (and nobody else's)."""
    is_platform_admin = True

    def __init__(self, email):
        self.email = email
