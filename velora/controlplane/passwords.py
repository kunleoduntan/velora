"""Password management for control-plane users: one standard policy, temporary passwords, and a simple, safe reset.

How a forgotten password is handled
  * Mail is set up    -> the person asks on the sign-in screen and receives a one-time link (valid 30 minutes, usable once). Nothing about the account is revealed.
  * Mail is NOT set up -> the request waits in the administrator's list. The administrator presses "Issue temporary password"; it is shown on THEIR screen for
                          a short time with a Copy button, and they pass it on. The temporary password must be changed at the first sign-in.
A temporary password is never shown to an anonymous requester (anyone could type someone else's email) and is never emailed.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, insert, select, update

from ..exceptions import CompanyAccessDenied, ValidationError
from . import models as m

LINK_MINUTES = 30
REQUESTS_PER_HOUR = 3
PENDING_DAYS = 7
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"       # no 0/O/1/l/I: easy to read out and to type
_COMMON = {"password", "passw0rd", "password1", "qwerty123", "letmein123", "welcome123", "admin12345", "changeme123", "1234567890", "iloveyou123", "abc1234567"}
GENERIC = "If that email belongs to an active account, the next step has been arranged."


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def policy_rules() -> dict:
    from .identity import PASSWORD_MIN
    return {"min_length": PASSWORD_MIN, "rules": [f"At least {PASSWORD_MIN} characters", "A mix of letters and numbers (or a long passphrase of 16+ characters)", "Not your email or name", "Not a common password"]}


def check_strength(password: str, email: str = "", name: str = "") -> None:
    """The one place the rules live. Length limits stay in identity; this adds the quality rules."""
    from .identity import PASSWORD_MAX, PASSWORD_MIN
    if len(password) < PASSWORD_MIN:
        raise ValidationError(f"Password must be at least {PASSWORD_MIN} characters")
    if len(password) > PASSWORD_MAX:
        raise ValidationError(f"Password must be at most {PASSWORD_MAX} characters")
    low = password.lower()
    if email and low == email.lower():
        raise ValidationError("Password must not be the same as the email address")
    if email and len(email.split("@")[0]) >= 4 and email.split("@")[0].lower() in low:
        raise ValidationError("Password must not contain your email name")
    if low in _COMMON or len(set(password)) <= 3:
        raise ValidationError("That password is too easy to guess. Choose something less common.")
    classes = sum(any(f(ch) for ch in password) for f in (str.islower, str.isupper, str.isdigit, lambda ch: not ch.isalnum()))
    if len(password) < 16 and (classes < 2 or not any(ch.isalpha() for ch in password) or not any(not ch.isalpha() for ch in password)):
        raise ValidationError("Use letters together with numbers or symbols, or a passphrase of 16 or more characters")


def temporary_password() -> str:
    """e.g. Kd7m-Qx4R-p9Wt : 12 random characters (about 68 bits), grouped for reading aloud."""
    while True:
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(12))
        if any(c.islower() for c in raw) and any(c.isupper() for c in raw) and any(c.isdigit() for c in raw):
            return "-".join(raw[i:i + 4] for i in range(0, 12, 4))


class Passwords:
    def __init__(self, plane):
        self.plane = plane
        self._ready = False
        self._cache: dict[str, tuple[float, bool]] = {}

    # ---- storage ------------------------------------------------------------------------------
    def _ensure(self):
        """Existing installations get the two small tables the first time they are needed."""
        if not self._ready:
            m.cp_metadata.create_all(self.plane.engine, tables=[m.password_state, m.password_reset])
            self._ready = True

    @staticmethod
    def _admin(actor):
        if not actor or not getattr(actor, "is_platform_admin", False):
            raise CompanyAccessDenied("Platform administrator permission is required")

    def must_change(self, user_id: str) -> bool:
        hit = self._cache.get(user_id)
        if hit and time.monotonic() - hit[0] < 3:
            return hit[1]
        self._ensure()
        with self.plane.engine.connect() as c:
            flag = bool(c.execute(select(m.password_state.c.must_change).where(m.password_state.c.user_id == user_id)).scalar())
        self._cache[user_id] = (time.monotonic(), flag)
        return flag

    def _set_state(self, c, user_id: str, must: bool, issued: bool = False):
        now = _now()
        values = dict(must_change=must, changed_on=None if must else now, temp_issued_on=now if issued else None)
        if c.execute(update(m.password_state).where(m.password_state.c.user_id == user_id).values(**values)).rowcount == 0:
            c.execute(insert(m.password_state).values(user_id=user_id, **values))
        self._cache.pop(user_id, None)

    def after_password_set(self, user_id: str):
        """Called when a person chooses their own password: the temporary flag is cleared."""
        self._ensure()
        with self.plane.engine.begin() as c:
            self._set_state(c, user_id, False)

    # ---- administrator: temporary password ------------------------------------------------------
    def issue_temporary(self, actor, user_id: str) -> dict:
        self._admin(actor)
        self._ensure()
        ident = self.plane.identity
        with self.plane.engine.connect() as c:
            u = c.execute(select(m.user).where(m.user.c.id == user_id)).mappings().first()
        if not u:
            raise ValidationError("No such user")
        if not u["is_active"]:
            raise ValidationError("This user is suspended. Activate the account first.")
        from .identity import hash_password
        password = temporary_password()
        with self.plane.engine.begin() as c:
            c.execute(update(m.user).where(m.user.c.id == user_id).values(password_hash=hash_password(password), failed_attempts=0, locked_until=None))
            c.execute(delete(m.session).where(m.session.c.user_id == user_id))
            self._set_state(c, user_id, True, issued=True)
            c.execute(update(m.password_reset).where(m.password_reset.c.user_id == user_id, m.password_reset.c.status.in_(("Pending", "Emailed")))
                      .values(status="Done", handled_by=actor.email, token_hash=None))
        self.plane.audit("password.temporary_issued", actor=actor.email, subject=u["email"])
        return {"user_id": user_id, "email": u["email"], "temporary_password": password, "must_change": True,
                "note": "Shown once. Give it to the person privately; they must choose a new password at their first sign-in."}

    # ---- forgot password --------------------------------------------------------------------------
    def mail_config(self) -> dict | None:
        cfg = (self.plane.ws.common_config().get("email") or {}) if getattr(self.plane, "ws", None) else {}
        return cfg if cfg.get("host") and cfg.get("from_addr") else None

    def request_reset(self, email: str, ip: str | None, base_url: str) -> dict:
        """Always answers the same way, whether or not the account exists."""
        self._ensure()
        email = (email or "").strip().lower()
        mail = self.mail_config()
        answer = {"message": GENERIC, "mode": "email" if mail else "administrator"}
        u = self.plane.identity.get_user(email) if email and len(email) <= 254 else None
        if not u or not u["is_active"]:
            return answer
        now = _now()
        with self.plane.engine.connect() as c:
            recent = c.execute(select(func.count()).select_from(m.password_reset).where(m.password_reset.c.user_id == u["id"], m.password_reset.c.requested_on > now - timedelta(hours=1))).scalar()
        if recent >= REQUESTS_PER_HOUR:
            self.plane.audit("password.reset_throttled", subject=email, detail={"ip": ip})
            return answer
        token = secrets.token_urlsafe(32) if mail else None
        row = dict(id=secrets.token_hex(16), user_id=u["id"], email=email, requested_on=now, status="Emailed" if mail else "Pending", token_hash=_hash(token) if token else None,
                   expires_on=now + (timedelta(minutes=LINK_MINUTES) if mail else timedelta(days=PENDING_DAYS)), ip=(ip or "")[:64])
        with self.plane.engine.begin() as c:
            c.execute(update(m.password_reset).where(m.password_reset.c.user_id == u["id"], m.password_reset.c.status.in_(("Pending", "Emailed"))).values(status="Dismissed", token_hash=None))
            c.execute(insert(m.password_reset).values(**row))
        self.plane.audit("password.reset_requested", subject=email, detail={"ip": ip, "mode": answer["mode"]})
        if mail:
            link = f"{base_url.rstrip('/')}/#/reset-password?token={token}"
            try:
                from velora_notify.channels import send_email
                send_email({"recipient": email, "subject": "Reset your password",
                            "body": f"Hello {u['full_name'] or ''},\n\nUse this link to choose a new password. It works once and expires in {LINK_MINUTES} minutes:\n{link}\n\nIf you did not ask for this, ignore this email; your password has not changed.",
                            "payload": {"link": link}}, {"email": mail})
            except Exception as e:  # noqa: BLE001 - the person is told nothing either way; the administrator sees the request and can issue a temporary password
                with self.plane.engine.begin() as c:
                    c.execute(update(m.password_reset).where(m.password_reset.c.id == row["id"]).values(status="Pending", token_hash=None))
                self.plane.audit("password.reset_mail_failed", subject=email, detail={"error": str(e)[:200]})
        return answer

    def complete_reset(self, token: str, new_password: str, ip: str | None = None) -> dict:
        self._ensure()
        now = _now()
        with self.plane.engine.connect() as c:
            r = c.execute(select(m.password_reset).where(m.password_reset.c.token_hash == _hash(token or ""), m.password_reset.c.status == "Emailed")).mappings().first() if token else None
        if not r or r["expires_on"] <= now:
            raise ValidationError("This reset link is not valid any more. Ask for a new one.")
        u = self.plane.identity.get_user(r["email"])
        if not u or not u["is_active"]:
            raise ValidationError("This reset link is not valid any more. Ask for a new one.")
        check_strength(new_password, u["email"], u.get("full_name") or "")
        with self.plane.engine.begin() as c:
            if not c.execute(update(m.password_reset).where(m.password_reset.c.id == r["id"], m.password_reset.c.status == "Emailed").values(status="Done", token_hash=None, handled_by=u["email"])).rowcount:
                raise ValidationError("This reset link is not valid any more. Ask for a new one.")
        self.plane.identity.set_password(u["email"], new_password, actor=u["email"])
        self.plane.audit("password.reset_completed", actor=u["email"], subject=u["email"], detail={"ip": ip})
        return {"reset": True}

    # ---- administrator: the waiting list ------------------------------------------------------------
    def pending_requests(self, actor) -> list[dict]:
        self._admin(actor)
        self._ensure()
        now = _now()
        with self.plane.engine.connect() as c:
            rows = c.execute(select(m.password_reset, m.user.c.full_name, m.user.c.id.label("uid")).join(m.user, m.user.c.id == m.password_reset.c.user_id)
                             .where(m.password_reset.c.status == "Pending", m.password_reset.c.expires_on > now).order_by(m.password_reset.c.requested_on.desc())).mappings().all()
        return [{"id": r["id"], "user_id": r["uid"], "email": r["email"], "full_name": r["full_name"], "requested_on": r["requested_on"].isoformat(), "ip": r["ip"]} for r in rows]

    def dismiss(self, actor, request_id: str) -> bool:
        self._admin(actor)
        self._ensure()
        with self.plane.engine.begin() as c:
            n = c.execute(update(m.password_reset).where(m.password_reset.c.id == request_id, m.password_reset.c.status == "Pending").values(status="Dismissed", handled_by=actor.email)).rowcount
        if n:
            self.plane.audit("password.reset_dismissed", actor=actor.email, subject=request_id)
        return bool(n)


class MustChangeMiddleware:
    """Pure ASGI. While a temporary password is in use, the only things the session may do are change the password, read who it is, and sign out."""
    ALLOWED = ("/api/auth/",)

    def __init__(self, app, plane, cookie: str):
        self.app, self.plane, self.cookie = app, plane, cookie
        self._any: tuple[float, bool] = (0.0, False)

    def _anyone_pending(self) -> bool:
        now = time.monotonic()
        if now - self._any[0] > 3:
            try:
                self.plane.passwords._ensure()
                with self.plane.engine.connect() as c:
                    flag = bool(c.execute(select(func.count()).select_from(m.password_state).where(m.password_state.c.must_change.is_(True))).scalar())
            except Exception:  # noqa: BLE001 - never take the server down for this check
                flag = False
            self._any = (now, flag)
        return self._any[1]

    def _token(self, scope) -> str | None:
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = headers.get(b"authorization", b"").decode("latin-1")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() or None
        for part in headers.get(b"cookie", b"").decode("latin-1").split(";"):
            k, _, v = part.strip().partition("=")
            if k == self.cookie:
                return v or None
        return None

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api") or path.startswith(self.ALLOWED) or not self._anyone_pending():
            return await self.app(scope, receive, send)
        token = self._token(scope)
        if token:
            with self.plane.engine.connect() as c:
                uid = c.execute(select(m.session.c.user_id).where(m.session.c.token_hash == _hash(token))).scalar()
            if uid and self.plane.passwords.must_change(uid):
                import json
                raw = json.dumps({"error": "PasswordChangeRequired", "message": "You signed in with a temporary password. Choose a new password to continue.", "details": None}).encode()
                await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]})
                return await send({"type": "http.response.body", "body": raw})
        await self.app(scope, receive, send)
