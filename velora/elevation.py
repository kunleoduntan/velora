"""Unlocking the Server Console: a second, short-lived proof that the person at the keyboard is the platform administrator.

Signing in is not enough to edit code or run SQL. The administrator re-enters their password (and authenticator code if they use one) and receives an
*elevation token* valid for ten minutes. The token is signed with a key derived from the master key and bound to that one sign-in session, so it cannot be
moved to another session or forged, and it works across several server processes because nothing is stored. Wrong passwords are throttled and audited.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time

from .exceptions import AuthenticationRequired, PermissionDenied

TTL_SECONDS = 600
HEADER = "x-velora-elevation"
_FAILS: dict[str, list[float]] = {}
_LOCK = threading.Lock()
MAX_FAILS, WINDOW = 5, 600


def _sign(plane, token_hash: str, expires: int) -> str:
    key = plane.secrets.derive_key("server-console-elevation")
    return hmac.new(key, f"{token_hash}:{expires}".encode(), hashlib.sha256).hexdigest()


def _throttle(email: str):
    now = time.time()
    with _LOCK:
        recent = [t for t in _FAILS.get(email, []) if now - t < WINDOW]
        _FAILS[email] = recent
        if len(recent) >= MAX_FAILS:
            raise PermissionDenied("Too many wrong passwords. Wait ten minutes before unlocking again.")


def _failed(email: str):
    with _LOCK:
        _FAILS.setdefault(email, []).append(time.time())


def unlock(plane, auth, password: str, totp_code: str | None = None) -> dict:
    """Check the password (and authenticator code) again and hand out a signed token."""
    from .controlplane.identity import totp_match, verify_password
    email = auth.email
    _throttle(email)
    user = plane.identity._need_user(email)
    if not verify_password(password or "", user["password_hash"]):
        _failed(email)
        plane.audit("console.unlock_failed", actor=email, subject=email)
        raise AuthenticationRequired("That password is not correct")
    if user.get("totp_enabled"):
        step = totp_match(plane.secrets.get(user["totp_secret_ref"]), str(totp_code or "")) if totp_code else None
        if step is None:
            _failed(email)
            plane.audit("console.unlock_failed", actor=email, subject=email, detail={"reason": "authenticator code"})
            raise AuthenticationRequired("Enter the current code from your authenticator app")
    expires = int(time.time()) + TTL_SECONDS
    plane.audit("console.unlocked", actor=email, subject=email, detail={"minutes": TTL_SECONDS // 60})
    return {"token": f"{expires}.{_sign(plane, auth.token_hash, expires)}", "expires_in": TTL_SECONDS}


def remaining(plane, auth, token: str | None) -> int:
    """Seconds left on a valid token for this session; 0 when there is none, it is forged, belongs to another session or has run out."""
    try:
        exp_s, sig = str(token or "").split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return 0
    left = exp - int(time.time())
    if left <= 0 or left > TTL_SECONDS + 5:
        return 0
    return left if hmac.compare_digest(sig, _sign(plane, auth.token_hash, exp)) else 0


def require(plane, auth, request) -> int:
    left = remaining(plane, auth, request.headers.get(HEADER))
    if not left:
        raise PermissionDenied("Unlock the Server Console first: this action needs your password again.")
    return left
