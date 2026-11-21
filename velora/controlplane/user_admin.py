"""v0.34 enterprise user administration and identity lifecycle controls.

All mutating methods require a platform-administrator AuthContext. New users are
created inactive and cannot authenticate until an administrator activates them.
Business roles remain tenant/company scoped in the company database; the
control plane stores only membership routing and legacy role labels.
"""
from __future__ import annotations

import secrets
from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from . import models as m
from .identity import _now, hash_password, EMAIL_RE
from .sso_provisioning import SSOProvisioner
from ..exceptions import CompanyAccessDenied, ValidationError


class UserAdministration:
    def __init__(self, plane):
        self.plane = plane
        self.engine = plane.engine

    @staticmethod
    def _admin(actor):
        if not actor or not getattr(actor, "is_platform_admin", False):
            raise CompanyAccessDenied("Platform administrator permission is required")

    def provision_user(self, actor, *, email: str, full_name: str = "", activate: bool = False) -> dict:
        self._admin(actor)
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise ValidationError("A valid email address is required")
        # Generate a high-entropy, undisclosed credential. The account remains
        # inactive by default and must complete an administrator-approved flow.
        row = dict(id=secrets.token_hex(16), email=email,
                   full_name=(full_name or email.split("@")[0]).strip()[:200],
                   password_hash=hash_password(secrets.token_urlsafe(48)),
                   is_active=bool(activate), is_platform_admin=False,
                   failed_attempts=0, created_on=_now())
        try:
            with self.engine.begin() as c:
                c.execute(insert(m.user).values(**row))
        except IntegrityError:
            raise ValidationError("A user with this email already exists") from None
        self.plane.audit("user.provision", actor=actor.email, subject=email,
                         detail={"activated": bool(activate)})
        return {"id": row["id"], "email": email, "full_name": row["full_name"],
                "is_active": bool(activate), "is_platform_admin": False}

    def list_users(self, actor, *, include_inactive: bool = True) -> list[dict]:
        self._admin(actor)
        stmt = select(m.user.c.id, m.user.c.email, m.user.c.full_name,
                      m.user.c.is_active, m.user.c.is_platform_admin,
                      m.user.c.created_on, m.user.c.last_login).order_by(m.user.c.email)
        if not include_inactive:
            stmt = stmt.where(m.user.c.is_active.is_(True))
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(stmt).mappings()]

    def update_profile(self, actor, user_id: str, *, full_name: str | None = None,
                       email: str | None = None) -> dict:
        self._admin(actor)
        values = {}
        if full_name is not None:
            name = full_name.strip()
            if not name or len(name) > 200:
                raise ValidationError("Full name must contain 1 to 200 characters")
            values["full_name"] = name
        if email is not None:
            normalized = email.strip().lower()
            if not EMAIL_RE.match(normalized):
                raise ValidationError("A valid email address is required")
            values["email"] = normalized
        if not values:
            raise ValidationError("No profile changes supplied")
        try:
            with self.engine.begin() as c:
                result = c.execute(update(m.user).where(m.user.c.id == user_id).values(**values))
                if not result.rowcount:
                    raise ValidationError("User not found")
        except IntegrityError:
            raise ValidationError("A user with this email already exists") from None
        self.plane.audit("user.profile_updated", actor=actor.email, subject=user_id,
                         detail={"fields": sorted(values)})
        with self.engine.connect() as c:
            row = c.execute(select(m.user.c.id, m.user.c.email, m.user.c.full_name,
                                   m.user.c.is_active).where(m.user.c.id == user_id)).mappings().first()
        return dict(row)

    def set_user_active(self, actor, user_id: str, active: bool) -> bool:
        self._admin(actor)
        with self.engine.begin() as c:
            row = c.execute(select(m.user.c.email, m.user.c.is_platform_admin)
                            .where(m.user.c.id == user_id)).mappings().first()
            if not row:
                raise ValidationError("User not found")
            if row["is_platform_admin"] and not active:
                admins = c.execute(select(m.user.c.id).where(and_(m.user.c.is_platform_admin.is_(True),
                                                                   m.user.c.is_active.is_(True)))).all()
                if len(admins) <= 1:
                    raise ValidationError("The last active platform administrator cannot be suspended")
            c.execute(update(m.user).where(m.user.c.id == user_id).values(is_active=bool(active),
                                                                           failed_attempts=0, locked_until=None))
            if not active:
                c.execute(delete(m.session).where(m.session.c.user_id == user_id))
        self.plane.audit("user.activated" if active else "user.suspended",
                         actor=actor.email, subject=row["email"])
        return True

    def grant_company_membership(self, actor, user_id: str, company_id: str,
                                 roles: list[str] | None = None) -> bool:
        self._admin(actor)
        roles = roles or []
        if not isinstance(roles, list) or any(not isinstance(x, str) or not x.strip() for x in roles):
            raise ValidationError("Roles must be a list of non-empty strings")
        with self.engine.begin() as c:
            u = c.execute(select(m.user.c.id).where(and_(m.user.c.id == user_id,
                                                         m.user.c.is_active.is_(True)))).first()
            co = c.execute(select(m.company.c.id).where(and_(m.company.c.id == company_id,
                                                              m.company.c.status == "active"))).first()
            if not u or not co:
                raise ValidationError("An active user and active company are required")
            exists = c.execute(select(m.user_company.c.user_id).where(and_(m.user_company.c.user_id == user_id,
                                                                            m.user_company.c.company_id == company_id))).first()
            if exists:
                c.execute(update(m.user_company).where(and_(m.user_company.c.user_id == user_id,
                                                            m.user_company.c.company_id == company_id)).values(roles=roles, granted_by=actor.email))
            else:
                c.execute(insert(m.user_company).values(user_id=user_id, company_id=company_id,
                                                        roles=roles, granted_on=_now(), granted_by=actor.email))
        self.plane.audit("membership.granted", actor=actor.email, subject=user_id,
                         detail={"company_id": company_id, "roles": roles})
        return True

    def revoke_company_membership(self, actor, user_id: str, company_id: str) -> bool:
        self._admin(actor)
        with self.engine.begin() as c:
            result = c.execute(delete(m.user_company).where(and_(m.user_company.c.user_id == user_id,
                                                                  m.user_company.c.company_id == company_id)))
            # Remove sessions currently pointing at this company. A user may
            # retain sessions for other authorized companies.
            c.execute(update(m.session).where(and_(m.session.c.user_id == user_id,
                                                   m.session.c.active_company_id == company_id)).values(active_company_id=None))
        self.plane.audit("membership.revoked", actor=actor.email, subject=user_id,
                         detail={"company_id": company_id})
        return bool(result.rowcount)

    def list_user_memberships(self, actor, user_id: str) -> list[dict]:
        self._admin(actor)
        with self.engine.connect() as c:
            rows = c.execute(select(m.user_company.c.company_id, m.company.c.tenant_id,
                                    m.company.c.name, m.company.c.status,
                                    m.user_company.c.roles, m.user_company.c.granted_on,
                                    m.user_company.c.granted_by)
                             .join(m.company, m.company.c.id == m.user_company.c.company_id)
                             .where(m.user_company.c.user_id == user_id)
                             .order_by(m.company.c.name)).mappings().all()
        return [dict(r) for r in rows]

    def revoke_all_sessions(self, actor, user_id: str) -> int:
        self._admin(actor)
        count = SSOProvisioner(self.plane).revoke_all_sessions(user_id)
        self.plane.audit("admin.sessions_revoked", actor=actor.email, subject=user_id)
        return count


    def list_user_sessions(self, actor, user_id: str) -> list[dict]:
        """Return session metadata only; bearer tokens and token hashes are never exposed."""
        self._admin(actor)
        with self.engine.connect() as c:
            rows = c.execute(select(m.session.c.created_on, m.session.c.expires_on,
                                    m.session.c.last_seen, m.session.c.active_company_id,
                                    m.session.c.ip, m.session.c.user_agent)
                             .where(m.session.c.user_id == user_id)
                             .order_by(m.session.c.created_on.desc())).mappings().all()
        return [dict(r) for r in rows]

    def revoke_session(self, actor, user_id: str, token_hash: str) -> bool:
        """Revoke one session using its hash supplied by a trusted admin client."""
        self._admin(actor)
        with self.engine.begin() as c:
            result = c.execute(delete(m.session).where(and_(m.session.c.user_id == user_id,
                                                             m.session.c.token_hash == token_hash)))
        if result.rowcount:
            self.plane.audit("admin.session_revoked", actor=actor.email, subject=user_id)
        return bool(result.rowcount)
