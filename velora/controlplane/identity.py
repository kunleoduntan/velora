"""Identity: users, passwords, sessions, and which companies a user may enter. Company roles live in each company database.

Security choices
  * passwords: scrypt (stdlib) with a per-user random salt; parameters are stored in the hash so they can be raised later
  * sessions: opaque random tokens; only their SHA-256 is stored, so a leaked database cannot be replayed
  * login errors never reveal whether the account exists; unknown users cost the same CPU as known ones
  * 5 wrong passwords lock the account for 15 minutes; changing a password revokes every session
  * every sign-in, failure, grant and company switch is written to cp_audit
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from ..exceptions import AuthenticationRequired, CompanyAccessDenied, CompanyUnavailable, ValidationError
from . import models as m

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
PASSWORD_MIN, PASSWORD_MAX = 10, 256
MAX_FAILED, LOCK_MINUTES = 5, 15
IP_MAX_FAILED, IP_WINDOW_MINUTES = 30, 15
SESSION_IDLE = timedelta(hours=12)       # sliding
SESSION_MAX = timedelta(days=7)          # hard cap
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_GENERIC = "Invalid email or password"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b = lambda x: base64.b64encode(x).decode()
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b(salt)}${b(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password("not-a-real-password")      # burned on unknown users so timing does not reveal them


def check_password_policy(password: str, email: str = ""):
    if len(password) < PASSWORD_MIN:
        raise ValidationError(f"Password must be at least {PASSWORD_MIN} characters")
    if len(password) > PASSWORD_MAX:
        raise ValidationError(f"Password must be at most {PASSWORD_MAX} characters")
    if email and password.lower() == email.lower():
        raise ValidationError("Password must not be the same as the email address")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class AuthContext:
    user_id: str
    email: str
    full_name: str
    is_platform_admin: bool
    token_hash: str
    active_company_id: str | None


@dataclass
class LoginResult:
    token: str
    context: AuthContext
    expires_on: datetime


class Identity:
    def __init__(self, plane):
        self.plane = plane

    @property
    def engine(self):
        return self.plane.engine

    # ---- users ----------------------------------------------------------------------------------
    def create_user(self, email: str, full_name: str, password: str, is_platform_admin: bool = False) -> dict:
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            raise ValidationError(f"{email!r} is not a valid email address")
        check_password_policy(password, email)
        row = dict(id=secrets.token_hex(16), email=email, full_name=full_name or email.split("@")[0], password_hash=hash_password(password),
                   is_active=True, is_platform_admin=is_platform_admin, failed_attempts=0, created_on=_now())
        try:
            with self.engine.begin() as c:
                c.execute(insert(m.user).values(**row))
        except IntegrityError:
            raise ValidationError(f"User {email} already exists") from None
        self.plane.audit("user.create", subject=email)
        return {k: row[k] for k in ("id", "email", "full_name", "is_platform_admin")}

    def get_user(self, email: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(m.user).where(m.user.c.email == email.strip().lower())).mappings().first()
        return dict(r) if r else None

    def list_users(self) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(select(m.user.c.email, m.user.c.full_name, m.user.c.is_active,
                                                      m.user.c.is_platform_admin, m.user.c.last_login).order_by(m.user.c.email)).mappings()]

    def set_password(self, email: str, password: str, actor: str = "cli"):
        u = self._need_user(email)
        check_password_policy(password, u["email"])
        with self.engine.begin() as c:
            c.execute(update(m.user).where(m.user.c.id == u["id"]).values(password_hash=hash_password(password), failed_attempts=0, locked_until=None))
            c.execute(delete(m.session).where(m.session.c.user_id == u["id"]))           # every session is revoked
        self.plane.audit("user.password_set", actor=actor, subject=u["email"])

    def change_password(self, auth: "AuthContext", current: str, new: str):
        u = self._need_user(auth.email)
        if not verify_password(current or "", u["password_hash"]):
            self.plane.audit("password.change_failed", actor=auth.email, subject=auth.email)
            raise AuthenticationRequired("Current password is incorrect")
        self.set_password(auth.email, new, actor=auth.email)        # also revokes every session: the user signs in again

    def set_active(self, email: str, active: bool):
        u = self._need_user(email)
        with self.engine.begin() as c:
            c.execute(update(m.user).where(m.user.c.id == u["id"]).values(is_active=active))
            if not active:
                c.execute(delete(m.session).where(m.session.c.user_id == u["id"]))
        self.plane.audit("user.activate" if active else "user.deactivate", subject=u["email"])

    def _need_user(self, email: str) -> dict:
        u = self.get_user(email)
        if not u:
            raise ValidationError(f"No such user: {email}")
        return u

    # ---- sign in / sessions ---------------------------------------------------------------------
    def _check_ip_limit(self, ip: str | None, now: datetime):
        if not ip:
            return
        with self.engine.connect() as c:
            row = c.execute(select(m.login_ip).where(m.login_ip.c.ip == ip[:64])).mappings().first()
        if row and row["blocked_until"] and row["blocked_until"] > now:
            raise AuthenticationRequired("Too many sign-in attempts from this network. Try again later.")

    def _record_ip_attempt(self, ip: str | None, success: bool, now: datetime):
        """Count a failed sign-in from this address. Every step is ONE atomic statement (parallel requests cannot lose counts), and two first failures arriving together cannot
        crash on the primary key. A success does not erase the count: otherwise one valid account would reset the limiter and let an attacker password-spray every other user."""
        if not ip or success:
            return
        key = ip[:64]
        fresh = now - timedelta(minutes=IP_WINDOW_MINUTES)
        for _ in range(3):
            with self.engine.begin() as c:
                hit = c.execute(update(m.login_ip).where(m.login_ip.c.ip == key, m.login_ip.c.window_started > fresh).values(attempts=m.login_ip.c.attempts + 1)).rowcount
                if hit:
                    if c.execute(select(m.login_ip.c.attempts).where(m.login_ip.c.ip == key)).scalar() >= IP_MAX_FAILED:
                        c.execute(update(m.login_ip).where(m.login_ip.c.ip == key).values(blocked_until=now + timedelta(minutes=IP_WINDOW_MINUTES)))
                    return
                if c.execute(update(m.login_ip).where(m.login_ip.c.ip == key).values(window_started=now, attempts=1, blocked_until=None)).rowcount:
                    return                                                              # the old window had expired: start a new one
            try:
                with self.engine.begin() as c:
                    c.execute(insert(m.login_ip).values(ip=key, window_started=now, attempts=1, blocked_until=None))
                return
            except IntegrityError:
                continue                                                                # another request just created it: count ours on top

    def _register_failure(self, user_id: str, now: datetime) -> int:
        """Count a failed password OR second-factor attempt against the ACCOUNT, atomically, and lock it after MAX_FAILED. (The count used to be read, +1 in Python, written back:
        a burst of parallel guesses all read the same number and the lock never came.)"""
        with self.engine.begin() as c:
            c.execute(update(m.user).where(m.user.c.id == user_id).values(failed_attempts=func.coalesce(m.user.c.failed_attempts, 0) + 1))
            fails = c.execute(select(m.user.c.failed_attempts).where(m.user.c.id == user_id)).scalar() or 0
            if fails >= MAX_FAILED:
                c.execute(update(m.user).where(m.user.c.id == user_id).values(failed_attempts=0, locked_until=now + timedelta(minutes=LOCK_MINUTES)))
        return fails

    def _claim_totp_step(self, user_id: str, step: int) -> bool:
        """Accept each 30-second code once: atomically record the step, and refuse it if it (or a later one) was already used. Two requests presenting the same code together: one wins."""
        with self.engine.begin() as c:
            return bool(c.execute(update(m.user).where(m.user.c.id == user_id, (m.user.c.totp_last_step.is_(None)) | (m.user.c.totp_last_step < step)).values(totp_last_step=step)).rowcount)

    def authenticate(self, email: str, password: str, ip: str | None = None, user_agent: str | None = None, totp_code: str | None = None) -> LoginResult:
        email = (email or "").strip().lower()
        u = self.get_user(email) if EMAIL_RE.match(email) and len(password or "") <= PASSWORD_MAX else None
        now = _now()
        self._check_ip_limit(ip, now)
        if u is None:
            verify_password(password or "", _DUMMY)
            self._record_ip_attempt(ip, False, now)
            self.plane.audit("login.failed", subject=email[:254], detail={"reason": "unknown", "ip": ip})
            raise AuthenticationRequired(_GENERIC)
        if u["locked_until"] and u["locked_until"] > now:
            self.plane.audit("login.blocked", subject=email, detail={"reason": "locked", "ip": ip})
            raise AuthenticationRequired("This account is temporarily locked after repeated failed sign-ins. Try again later.")
        ok = verify_password(password, u["password_hash"])
        if not ok or not u["is_active"]:
            if not ok:
                self._register_failure(u["id"], now)
            self._record_ip_attempt(ip, False, now)
            self.plane.audit("login.failed", subject=email, detail={"reason": "password" if not ok else "inactive", "ip": ip})
            raise AuthenticationRequired(_GENERIC)
        if u.get("totp_enabled"):
            if not totp_code:
                raise AuthenticationRequired("Enter the six-digit authenticator code to continue")
            secret = self.plane.secrets.get(u["totp_secret_ref"])
            step = totp_match(secret, str(totp_code))
            if step is None or not self._claim_totp_step(u["id"], step):
                self._register_failure(u["id"], now)                    # the second factor counts against the ACCOUNT too: 6 digits must not be guessable at leisure
                self._record_ip_attempt(ip, False, now)
                self.plane.audit("login.mfa_failed", subject=email, detail={"ip": ip, "reason": "invalid" if step is None else "replayed"})
                raise AuthenticationRequired("The authenticator code is invalid")
        self._record_ip_attempt(ip, True, now)
        token = secrets.token_urlsafe(32)
        expires = now + SESSION_IDLE
        with self.engine.begin() as c:
            c.execute(update(m.user).where(m.user.c.id == u["id"]).values(failed_attempts=0, locked_until=None, last_login=now))
            c.execute(insert(m.session).values(token_hash=_token_hash(token), user_id=u["id"], created_on=now, expires_on=expires,
                                               last_seen=now, ip=(ip or "")[:64], user_agent=(user_agent or "")[:300]))
        self.plane.audit("login.ok", actor=email, subject=email, detail={"ip": ip})
        return LoginResult(token, AuthContext(u["id"], email, u["full_name"], bool(u["is_platform_admin"]), _token_hash(token), None), expires)

    def resolve(self, token: str | None) -> AuthContext:
        if not token:
            raise AuthenticationRequired("Sign in required")
        th, now = _token_hash(token), _now()
        with self.engine.connect() as c:
            r = c.execute(select(m.session, m.user.c.email, m.user.c.full_name, m.user.c.is_active, m.user.c.is_platform_admin)
                          .join(m.user, m.user.c.id == m.session.c.user_id).where(m.session.c.token_hash == th)).mappings().first()
        if r is None or r["expires_on"] <= now or r["created_on"] + SESSION_MAX <= now or not r["is_active"]:
            if r is not None:
                with self.engine.begin() as c:
                    c.execute(delete(m.session).where(m.session.c.token_hash == th))
            raise AuthenticationRequired("Your session has expired. Sign in again.")
        if r["last_seen"] is None or now - r["last_seen"] > timedelta(seconds=60):        # slide the expiry without a write per request
            with self.engine.begin() as c:
                c.execute(update(m.session).where(m.session.c.token_hash == th).values(last_seen=now, expires_on=min(now + SESSION_IDLE, r["created_on"] + SESSION_MAX)))
        return AuthContext(r["user_id"], r["email"], r["full_name"], bool(r["is_platform_admin"]), th, r["active_company_id"])

    def logout(self, token: str | None):
        if token:
            with self.engine.begin() as c:
                c.execute(delete(m.session).where(m.session.c.token_hash == _token_hash(token)))

    # ---- company access -------------------------------------------------------------------------
    def grant(self, email: str, company_id: str, roles: list[str], actor: str = "cli"):
        u, co = self._need_user(email), self.plane.registry.get_company(company_id)
        if co is None:
            raise ValidationError(f"No such company: {company_id}")
        roles = sorted({r.strip() for r in roles if r.strip()})
        if not roles:
            raise ValidationError("Give at least one role")
        # Company membership is indexed in the Control Plane; the actual role assignment is
        # stored in the company's own operational database.
        from .. import site as site_mod
        from ..db.system import company_user_role
        from sqlalchemy import insert as sa_insert, update as sa_update
        site = self.plane.router.site_for(co)
        with site_mod.use(site):
            company_user_role.create(site.engine, checkfirst=True)
            with site.engine.begin() as conn:
                existing_role = conn.execute(select(company_user_role.c.user_email).where(company_user_role.c.user_email == u["email"])).first()
                if existing_role:
                    conn.execute(sa_update(company_user_role).where(company_user_role.c.user_email == u["email"]).values(roles=roles, granted_by=actor, granted_on=_now()))
                else:
                    conn.execute(sa_insert(company_user_role).values(user_email=u["email"], roles=roles, granted_by=actor, granted_on=_now()))
        with self.engine.begin() as c:
            exists = c.execute(select(m.user_company.c.user_id).where(and_(m.user_company.c.user_id == u["id"], m.user_company.c.company_id == company_id))).first()
            if exists:
                c.execute(update(m.user_company).where(and_(m.user_company.c.user_id == u["id"], m.user_company.c.company_id == company_id)).values(roles=[]))
            else:
                c.execute(insert(m.user_company).values(user_id=u["id"], company_id=company_id, roles=[], granted_on=_now(), granted_by=actor))
        self.plane.audit("access.grant", actor=actor, subject=u["email"], detail={"company": company_id, "roles": roles})

    def revoke(self, email: str, company_id: str, actor: str = "cli"):
        u = self._need_user(email)
        co = self.plane.registry.get_company(company_id)
        if co:
            from .. import site as site_mod
            from ..db.system import company_user_role
            try:
                site = self.plane.router.site_for(co)
                with site_mod.use(site):
                    company_user_role.create(site.engine, checkfirst=True)
                    with site.engine.begin() as conn:
                        conn.execute(delete(company_user_role).where(company_user_role.c.user_email == u["email"]))
            except Exception:
                pass
        with self.engine.begin() as c:
            c.execute(delete(m.user_company).where(and_(m.user_company.c.user_id == u["id"], m.user_company.c.company_id == company_id)))
            c.execute(update(m.session).where(and_(m.session.c.user_id == u["id"], m.session.c.active_company_id == company_id)).values(active_company_id=None))
        self.plane.audit("access.revoke", actor=actor, subject=u["email"], detail={"company": company_id})

    def companies_for(self, user_id: str) -> list[dict]:
        """Companies this user may enter, with the roles they hold in each (suspended ones are listed but flagged)."""
        with self.engine.connect() as c:
            rows = c.execute(select(m.company.c.id, m.company.c.name, m.company.c.status, m.company.c.tenant_id, m.tenant.c.name.label("tenant_name"), m.user_company.c.roles, m.user.c.email)
                             .join(m.user_company, m.user_company.c.company_id == m.company.c.id)
                             .join(m.user, m.user.c.id == m.user_company.c.user_id)
                             .join(m.tenant, m.tenant.c.id == m.company.c.tenant_id)
                             .where(m.user_company.c.user_id == user_id).order_by(m.tenant.c.name, m.company.c.name)).mappings().all()
        out = []
        for raw in rows:
            item = dict(raw)
            co = self.plane.registry.get_company(item["id"])
            item["roles"] = self._company_roles(co, item.get("roles") or [], user_email=item.get("email")) if co else []
            out.append(item)
        return out

    def _company_roles(self, company: dict, legacy_roles: list[str] | None = None, user_email: str | None = None) -> list[str]:
        if not company or not user_email:
            return list(legacy_roles or [])
        from .. import site as site_mod
        from ..db.system import company_user_role
        try:
            site = self.plane.router.site_for(company)
            with site_mod.use(site):
                company_user_role.create(site.engine, checkfirst=True)
                with site.engine.connect() as conn:
                    row = conn.execute(select(company_user_role.c.roles).where(company_user_role.c.user_email == user_email)).first()
                if row:
                    return list(row[0] or [])
                # Migrate legacy Control Plane roles into this company's database once.
                if legacy_roles:
                    with site.engine.begin() as conn:
                        conn.execute(company_user_role.insert().values(user_email=user_email, roles=list(legacy_roles), granted_by="legacy-migration", granted_on=_now()))
                    return list(legacy_roles)
                return []
        except Exception:
            return list(legacy_roles or [])

    def authorize(self, auth: AuthContext, company_id: str | None) -> tuple[dict, list[str]]:
        """Validate that `auth` may work in `company_id` right now. Returns (company row, roles in that company)."""
        mine = {c["id"]: c for c in self.companies_for(auth.user_id)}
        if company_id is None:
            company_id = auth.active_company_id if auth.active_company_id in mine else (next(iter(mine)) if len(mine) == 1 else None)
        if company_id is None:
            raise CompanyAccessDenied("Select a company to work in" if mine else "You have not been given access to any company")
        entry = mine.get(company_id)
        if entry is None:
            raise CompanyAccessDenied("You do not have access to this company")        # same message whether it exists or not
        tenant = self.plane.registry.get_tenant(entry["tenant_id"])
        if not tenant or tenant.get("status") != "active":
            raise CompanyUnavailable("This tenant is suspended")
        if entry["status"] != "active":
            raise CompanyUnavailable(f"This company is {entry['status']}")
        return self.plane.registry.get_company(company_id), list(entry["roles"])

    # ---- a person's default company (used when they sign in; kept in cp_meta, no schema change) ----
    def default_company(self, user_id: str) -> str | None:
        with self.engine.connect() as c:
            row = c.execute(select(m.meta.c.value).where(m.meta.c.key == f"default_company:{user_id}")).first()
        return row[0] if row and row[0] else None

    def set_default_company(self, auth: AuthContext, company_id: str | None) -> str | None:
        """Remember `company_id` as this person's default. They must have access to it (an empty value clears it)."""
        key = f"default_company:{auth.user_id}"
        if company_id:
            if company_id not in {c["id"] for c in self.companies_for(auth.user_id)}:
                raise CompanyAccessDenied("You do not have access to this company")
        with self.engine.begin() as c:
            c.execute(delete(m.meta).where(m.meta.c.key == key))
            if company_id:
                c.execute(insert(m.meta).values(key=key, value=company_id))
        self.plane.audit("company.default", actor=auth.email, subject=company_id or "(cleared)")
        return company_id or None

    def switch_company(self, auth: AuthContext, company_id: str) -> dict:
        company, roles = self.authorize(auth, company_id)
        with self.engine.begin() as c:
            c.execute(update(m.session).where(m.session.c.token_hash == auth.token_hash).values(active_company_id=company_id))
        self.plane.audit("company.switch", actor=auth.email, subject=company_id)
        return {"id": company["id"], "name": company["name"], "roles": roles}


    # ---- optional authenticator-app MFA ---------------------------------------------------------
    def begin_totp(self, auth: "AuthContext", issuer: str = "Velora") -> dict:
        """Create a pending TOTP secret. MFA is opt-in and does not affect users until confirmed."""
        secret = base64.b32encode(os.urandom(20)).decode().rstrip("=")
        ref = self.plane.secrets.put(secret)
        u = self._need_user(auth.email)
        old = u.get("totp_pending_ref")
        with self.engine.begin() as c:
            c.execute(update(m.user).where(m.user.c.id == u["id"]).values(totp_pending_ref=ref))
        if old:
            self.plane.secrets.delete(old)
        label = f"{issuer}:{auth.email}"
        uri = f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
        self.plane.audit("mfa.setup_started", actor=auth.email, subject=auth.email)
        return {"secret": secret, "otpauth_uri": uri}

    def confirm_totp(self, auth: "AuthContext", code: str):
        u = self._need_user(auth.email)
        if not u.get("totp_pending_ref"):
            raise ValidationError("Start authenticator setup before confirming it")
        secret = self.plane.secrets.get(u["totp_pending_ref"])
        step = totp_match(secret, code)
        if step is None:
            raise ValidationError("The authenticator code is not valid")
        old = u.get("totp_secret_ref")
        with self.engine.begin() as c:
            c.execute(update(m.user).where(m.user.c.id == u["id"]).values(totp_secret_ref=u["totp_pending_ref"], totp_pending_ref=None, totp_enabled=True, totp_last_step=step))
        if old:
            self.plane.secrets.delete(old)
        self.plane.audit("mfa.enabled", actor=auth.email, subject=auth.email)

    def disable_totp(self, auth: "AuthContext", password: str):
        u = self._need_user(auth.email)
        if not verify_password(password or "", u["password_hash"]):
            raise AuthenticationRequired("Password confirmation failed")
        refs = [u.get("totp_secret_ref"), u.get("totp_pending_ref")]
        with self.engine.begin() as c:
            c.execute(update(m.user).where(m.user.c.id == u["id"]).values(totp_secret_ref=None, totp_pending_ref=None, totp_enabled=False))
        for ref in refs:
            if ref:
                self.plane.secrets.delete(ref)
        self.plane.audit("mfa.disabled", actor=auth.email, subject=auth.email)


def _totp_counter(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"

def totp_match(secret: str, code: str, at: datetime | None = None) -> int | None:
    """The 30-second step the code belongs to (within one step either side of now), or None. Every candidate is compared in constant time."""
    code = re.sub(r"\s+", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    counter = int((at or datetime.now(timezone.utc)).timestamp() // 30)
    matched = None
    for delta in (-1, 0, 1):
        if hmac.compare_digest(_totp_counter(secret, counter + delta), code):
            matched = counter + delta
    return matched


def verify_totp(secret: str, code: str, at: datetime | None = None) -> bool:
    return totp_match(secret, code, at) is not None
