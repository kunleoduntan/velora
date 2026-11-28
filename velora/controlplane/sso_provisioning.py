"""v0.33: verified SSO identity linking, opt-in provisioning, and session lifecycle.

Email is never sufficient to link an existing account: an administrator must
pre-link it. All identities are scoped by issuer and immutable subject.
"""
from __future__ import annotations
import secrets
from sqlalchemy import Table, Column, String, DateTime, select, insert, delete, and_
from .models import cp_metadata, user, user_company, session, company
from .identity import _now, _token_hash, SESSION_IDLE
from ..exceptions import AuthenticationRequired, CompanyAccessDenied, ValidationError

sso_link = Table('cp_sso_link', cp_metadata,
    Column('issuer', String(500), primary_key=True),
    Column('subject', String(500), primary_key=True),
    Column('user_id', String(32), nullable=False, index=True),
    Column('linked_on', DateTime, nullable=False))

class SSOProvisioner:
    def __init__(self, plane):
        self.plane = plane
        self.engine = plane.engine

    def ensure_schema(self):
        sso_link.create(self.engine, checkfirst=True)

    def link_existing(self, *, issuer, subject, user_id, actor='admin'):
        if not issuer or not subject or not user_id:
            raise ValidationError('Issuer, subject and user ID are required')
        self.ensure_schema()
        with self.engine.begin() as c:
            u = c.execute(select(user).where(and_(user.c.id == user_id, user.c.is_active == True))).mappings().first()
            if not u:
                raise ValidationError('Active user not found')
            old = c.execute(select(sso_link.c.user_id).where(and_(sso_link.c.issuer == issuer, sso_link.c.subject == subject))).scalar_one_or_none()
            if old and old != user_id:
                raise ValidationError('Identity is already linked to another user')
            if not old:
                c.execute(insert(sso_link).values(issuer=issuer, subject=subject, user_id=user_id, linked_on=_now()))
        self.plane.audit('sso.link', actor=actor, subject=user_id, detail={'issuer': issuer})

    def resolve_identity(self, identity: dict, tenant_id: str) -> str:
        issuer = identity.get('issuer')
        subject = identity.get('subject')
        if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
            raise AuthenticationRequired('Verified issuer and subject are required')
        self.ensure_schema()
        with self.engine.connect() as c:
            u = c.execute(select(user).join(sso_link, sso_link.c.user_id == user.c.id)
                .where(and_(sso_link.c.issuer == issuer, sso_link.c.subject == subject))).mappings().first()
            if not u or not u['is_active']:
                raise AuthenticationRequired('SSO identity has not been linked to an active account')
            # Tenant membership is mandatory even for platform administrators.
            membership = c.execute(select(user_company.c.user_id).join(company,
                user_company.c.company_id == company.c.id)
                .where(and_(user_company.c.user_id == u['id'], company.c.tenant_id == tenant_id))).first()
            if not membership:
                raise CompanyAccessDenied('No membership in requested tenant')
        return u['id']

    def issue_session(self, user_id: str, tenant_id: str, *, ip=None, user_agent=None) -> str:
        from .models import company
        now = _now()
        token = secrets.token_urlsafe(32)
        with self.engine.begin() as c:
            u = c.execute(select(user).where(and_(user.c.id == user_id, user.c.is_active == True))).mappings().first()
            if not u:
                raise AuthenticationRequired('Inactive or missing account')
            co = c.execute(select(company.c.id).join(user_company, user_company.c.company_id == company.c.id)
                .where(and_(user_company.c.user_id == user_id, company.c.tenant_id == tenant_id,
                            company.c.status == 'active'))).first()
            if not co:
                raise CompanyAccessDenied('No active company membership for tenant')
            c.execute(insert(session).values(token_hash=_token_hash(token), user_id=user_id,
                created_on=now, expires_on=now + SESSION_IDLE, last_seen=now,
                active_company_id=co[0], ip=(ip or '')[:64], user_agent=(user_agent or '')[:300]))
        self.plane.audit('sso.session_created', actor=u['email'], subject=user_id, detail={'tenant_id': tenant_id})
        return token

    def list_sessions(self, user_id: str) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(session.c.token_hash, session.c.created_on,
                session.c.expires_on, session.c.last_seen, session.c.active_company_id,
                session.c.ip, session.c.user_agent).where(session.c.user_id == user_id)).mappings()]

    def revoke_session(self, user_id: str, token_hash: str):
        with self.engine.begin() as c:
            count = c.execute(delete(session).where(and_(session.c.user_id == user_id,
                session.c.token_hash == token_hash))).rowcount
        return bool(count)

    def revoke_all_sessions(self, user_id: str):
        with self.engine.begin() as c:
            count = c.execute(delete(session).where(session.c.user_id == user_id)).rowcount
        self.plane.audit('session.revoke_all', subject=user_id)
        return count
