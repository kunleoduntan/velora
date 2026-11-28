"""End-to-end OIDC SSO runtime for Velora v0.32.

The router deliberately requires injected provider transport, identity resolver,
and session issuer. This keeps account provisioning and session policy inside the
host application's trusted security boundary.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from ..exceptions import AuthenticationRequired, ValidationError
from .oidc_client import OIDCProviderClient


BIND_COOKIE = "velora_sso_bind"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _safe_return_path(value: str | None) -> str:
    # Only local absolute paths. Reject scheme-relative and backslash variants AND every control character: browsers silently DELETE tabs and newlines from a URL,
    # so "/<TAB>/evil.example" would be sent as "//evil.example" (another site).
    if not value:
        return "/"
    if not value.startswith("/") or value.startswith("//") or "\\" in value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return "/"
    return value


@dataclass(frozen=True)
class SSOProvider:
    slug: str
    issuer: str
    client_id: str
    redirect_uri: str
    allowed_hosts: frozenset[str]
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    client_secret: str | None = None

    def __post_init__(self):
        if not self.slug or not self.client_id or not self.redirect_uri.startswith("https://"):
            raise ValidationError("SSO provider requires slug, client ID and HTTPS callback URI")
        if not self.allowed_hosts:
            raise ValidationError("SSO provider requires an explicit HTTPS host allowlist")


class OIDCTransactionStore:
    """SQLite-backed, single-use OIDC transactions safe across app workers."""
    def __init__(self, database: str | Path, *, clock: Callable[[], float] = time.time):
        self.database, self.clock = str(database), clock
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS oidc_transactions (
                state_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, tenant_id TEXT NOT NULL,
                nonce TEXT NOT NULL, verifier TEXT NOT NULL, return_to TEXT NOT NULL,
                expires_at REAL NOT NULL, created_at REAL NOT NULL, binding_hash TEXT NOT NULL DEFAULT '')""")
            if "binding_hash" not in {r[1] for r in db.execute("PRAGMA table_info(oidc_transactions)")}:
                db.execute("ALTER TABLE oidc_transactions ADD COLUMN binding_hash TEXT NOT NULL DEFAULT ''")      # a store created before the browser binding existed
            db.execute("CREATE INDEX IF NOT EXISTS ix_oidc_transactions_expiry ON oidc_transactions(expires_at)")

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10, isolation_level="IMMEDIATE")
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _hash_state(state: str) -> str:
        return hashlib.sha256(state.encode()).hexdigest()

    def create(self, *, state: str, provider: str, tenant_id: str, nonce: str,
               verifier: str, return_to: str, ttl_seconds: int = 300, binding: str | None = None) -> None:
        """`binding` is a secret the STARTING browser also holds (a cookie): the callback must present it, so a login someone else started cannot be completed in your browser."""
        now = self.clock()
        with self._connect() as db:
            db.execute("DELETE FROM oidc_transactions WHERE expires_at <= ?", (now,))
            db.execute("INSERT INTO oidc_transactions (state_hash, provider, tenant_id, nonce, verifier, return_to, expires_at, created_at, binding_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (self._hash_state(state), provider, tenant_id, nonce, verifier,
                        _safe_return_path(return_to), now + ttl_seconds, now, self._hash_state(binding) if binding else ""))

    def consume(self, state: str, *, provider: str, binding: str | None = None) -> dict:
        """Take the transaction, exactly once. The row is removed in the SAME statement that reads it, so two simultaneous callbacks cannot both succeed (a SELECT followed by a
        DELETE let both through), and a transaction that fails the browser check is burned too: guessing is not free."""
        if not state:
            raise AuthenticationRequired("Missing OIDC state")
        now = self.clock()
        with self._connect() as db:
            if sqlite3.sqlite_version_info >= (3, 35, 0):
                row = db.execute("DELETE FROM oidc_transactions WHERE state_hash=? AND provider=? RETURNING *", (self._hash_state(state), provider)).fetchone()
            else:                                                                      # older SQLite: take the write lock first, then read and delete
                db.execute("BEGIN IMMEDIATE") if not db.in_transaction else None
                row = db.execute("SELECT * FROM oidc_transactions WHERE state_hash=? AND provider=?", (self._hash_state(state), provider)).fetchone()
                if row is not None:
                    db.execute("DELETE FROM oidc_transactions WHERE state_hash=?", (row["state_hash"],))
        if row is None or row["expires_at"] <= now:
            raise AuthenticationRequired("OIDC state is invalid, expired or already used")
        if row["binding_hash"] and not (binding and hmac.compare_digest(row["binding_hash"], self._hash_state(binding))):
            raise AuthenticationRequired("This sign-in was not started in this browser")
        return dict(row)


def create_sso_router(*, providers: Mapping[str, SSOProvider], transaction_store: OIDCTransactionStore,
                      provider_client_factory: Callable[[SSOProvider], OIDCProviderClient],
                      resolve_identity: Callable[[dict, str], str],
                      issue_session: Callable[[str, str], str],
                      cookie_name: str = "velora_session", cookie_domain: str | None = None,
                      cookie_secure: bool = True) -> APIRouter:
    """Build login/callback routes.

    resolve_identity(verified_identity, tenant_id) must securely link or provision
    the user and return an internal user ID. issue_session(user_id, tenant_id)
    must return a signed, expiring application session token.
    """
    router = APIRouter(prefix="/sso", tags=["SSO"])

    @router.get("/{provider}/login")
    def login(provider: str, tenant_id: str = Query(min_length=1, max_length=128),
              return_to: str = Query(default="/", max_length=2048)):
        config = providers.get(provider)
        if config is None:
            raise HTTPException(404, "Unknown identity provider")
        try:
            client = provider_client_factory(config)
            metadata = client.load_metadata()
            state, nonce = _b64u(secrets.token_bytes(32)), _b64u(secrets.token_bytes(32))
            verifier = _b64u(secrets.token_bytes(48))
            challenge = _b64u(hashlib.sha256(verifier.encode("ascii")).digest())
            binding = _b64u(secrets.token_bytes(32))
            transaction_store.create(state=state, provider=provider, tenant_id=tenant_id,
                                     nonce=nonce, verifier=verifier, return_to=return_to, binding=binding)
            params = {"response_type": "code", "client_id": config.client_id,
                      "redirect_uri": config.redirect_uri, "scope": " ".join(config.scopes),
                      "state": state, "nonce": nonce, "code_challenge": challenge,
                      "code_challenge_method": "S256"}
            response = RedirectResponse(metadata.discovery.authorization_endpoint + "?" + urlencode(params), status_code=302)
            response.set_cookie(BIND_COOKIE, binding, httponly=True, secure=cookie_secure, samesite="lax", path=f"/sso/{provider}", max_age=300)
            return response
        except (AuthenticationRequired, ValidationError) as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.get("/{provider}/callback")
    def callback(provider: str, request: Request, code: str | None = None,
                 state: str | None = None, error: str | None = None):
        config = providers.get(provider)
        if config is None:
            raise HTTPException(404, "Unknown identity provider")
        if error:
            raise HTTPException(401, "Identity provider rejected authentication")
        if not code or not state:
            raise HTTPException(400, "OIDC callback requires code and state")
        try:
            tx = transaction_store.consume(state, provider=provider, binding=request.cookies.get(BIND_COOKIE))
            client = provider_client_factory(config)
            metadata = client.load_metadata()
            identity = client.exchange_and_verify(code=code, redirect_uri=config.redirect_uri,
                    code_verifier=tx["verifier"], nonce=tx["nonce"], metadata=metadata)
            user_id = resolve_identity(identity, tx["tenant_id"])
            if not user_id:
                raise AuthenticationRequired("Identity could not be linked to an active tenant user")
            session_token = issue_session(str(user_id), tx["tenant_id"])
            if not session_token:
                raise AuthenticationRequired("Application session could not be issued")
            response = RedirectResponse(tx["return_to"], status_code=303)
            response.set_cookie(cookie_name, session_token, httponly=True, secure=cookie_secure,
                                samesite="lax", path="/", domain=cookie_domain, max_age=3600)
            response.delete_cookie(BIND_COOKIE, path=f"/sso/{provider}")
            return response
        except (AuthenticationRequired, ValidationError) as exc:
            raise HTTPException(401, str(exc)) from exc

    return router
