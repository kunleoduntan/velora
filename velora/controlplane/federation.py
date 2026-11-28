"""OIDC federation primitives for Velora v0.29.

This module creates PKCE-protected authorization requests and validates the
claims returned by a trusted OIDC adapter. The adapter MUST verify the ID-token
signature against the provider JWKS, enforce the allowed signing algorithm,
and validate token time claims before calling ``validate_verified_claims``.
Velora deliberately does not implement JWT cryptography itself.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

from ..exceptions import AuthenticationRequired, ValidationError


@dataclass(frozen=True)
class OIDCProvider:
    provider_id: str
    issuer: str
    authorization_endpoint: str
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "email", "profile")

    def validate(self) -> None:
        if not self.provider_id or not self.client_id:
            raise ValidationError("OIDC provider ID and client ID are required")
        for label, value in (("issuer", self.issuer), ("authorization endpoint", self.authorization_endpoint), ("redirect URI", self.redirect_uri)):
            parsed = urlparse(value or "")
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValidationError(f"OIDC {label} must be an absolute HTTPS URL")
        if not self.scopes or "openid" not in self.scopes:
            raise ValidationError("OIDC scopes must include openid")


@dataclass(frozen=True)
class OIDCLoginRequest:
    state: str
    nonce: str
    code_verifier: str
    authorization_url: str
    expires_at: int


class OIDCFederation:
    """Short-lived, one-use OIDC login transactions held server-side."""
    def __init__(self, providers: dict[str, OIDCProvider], transaction_ttl: int = 300, clock=time.time):
        if transaction_ttl < 60 or transaction_ttl > 900:
            raise ValidationError("OIDC transaction TTL must be between 60 and 900 seconds")
        self.providers = dict(providers)
        for provider in self.providers.values():
            provider.validate()
        self.transaction_ttl, self.clock = transaction_ttl, clock
        self._pending: dict[str, dict] = {}

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def begin(self, provider_id: str) -> OIDCLoginRequest:
        provider = self.providers.get(provider_id)
        if not provider:
            raise ValidationError("Unknown identity provider")
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier = self._b64(secrets.token_bytes(32)) + self._b64(secrets.token_bytes(16))
        challenge = self._b64(hashlib.sha256(verifier.encode("ascii")).digest())
        expires = int(self.clock()) + self.transaction_ttl
        self._pending[state] = {"provider_id": provider_id, "nonce": nonce, "verifier": verifier, "expires": expires}
        params = urlencode({"client_id": provider.client_id, "response_type": "code", "redirect_uri": provider.redirect_uri,
                            "scope": " ".join(provider.scopes), "state": state, "nonce": nonce,
                            "code_challenge": challenge, "code_challenge_method": "S256"})
        joiner = "&" if "?" in provider.authorization_endpoint else "?"
        return OIDCLoginRequest(state, nonce, verifier, provider.authorization_endpoint + joiner + params, expires)

    def consume(self, state: str, provider_id: str) -> dict:
        """Consume transaction exactly once; return verifier/nonce for token exchange."""
        item = self._pending.pop(state or "", None)
        if not item or item["provider_id"] != provider_id or item["expires"] < int(self.clock()):
            raise AuthenticationRequired("OIDC sign-in transaction is invalid or expired")
        return {"nonce": item["nonce"], "code_verifier": item["verifier"]}

    def validate_verified_claims(self, provider_id: str, claims: dict, expected_nonce: str) -> dict:
        """Validate claims only AFTER an OIDC adapter has cryptographically verified the ID token."""
        provider = self.providers.get(provider_id)
        if not provider:
            raise AuthenticationRequired("Unknown identity provider")
        now = int(self.clock())
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if claims.get("iss") != provider.issuer or provider.client_id not in audiences:
            raise AuthenticationRequired("OIDC issuer or audience validation failed")
        if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= now:
            raise AuthenticationRequired("OIDC identity token has expired")
        if not claims.get("sub") or not secrets.compare_digest(str(claims.get("nonce", "")), expected_nonce):
            raise AuthenticationRequired("OIDC subject or nonce validation failed")
        if claims.get("email_verified") is not True or not claims.get("email"):
            raise AuthenticationRequired("Identity provider must supply a verified email address")
        return {"provider_id": provider_id, "issuer": provider.issuer, "subject": str(claims["sub"]),
                "email": str(claims["email"]).strip().lower(), "name": str(claims.get("name") or "")}

    def prune(self) -> int:
        now = int(self.clock())
        expired = [key for key, value in self._pending.items() if value["expires"] < now]
        for key in expired:
            del self._pending[key]
        return len(expired)
