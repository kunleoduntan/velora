"""Cryptographic OIDC ID-token verification for Velora v0.30.

The caller supplies trusted discovery/JWKS documents (normally fetched over
HTTPS by the deployment's HTTP client). This module verifies compact JWTs
locally, pins issuer/audience/nonce, and supports RS256 and ES256 only.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from ..exceptions import AuthenticationRequired, ValidationError

_ALLOWED_ALGORITHMS = {"RS256", "ES256"}


def _b64u(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid base64url")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _json_segment(value: str) -> dict:
    obj = json.loads(_b64u(value))
    if not isinstance(obj, dict):
        raise ValueError("JWT segment must be an object")
    return obj


def _https_url(value: str, label: str) -> None:
    parsed = urlparse(value or "")
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValidationError(f"OIDC {label} must be an absolute HTTPS URL")


@dataclass(frozen=True)
class OIDCDiscovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str

    @classmethod
    def from_document(cls, expected_issuer: str, document: dict) -> "OIDCDiscovery":
        _https_url(expected_issuer, "issuer")
        if document.get("issuer") != expected_issuer:
            raise ValidationError("OIDC discovery issuer does not match configured issuer")
        values = [document.get(k) for k in ("authorization_endpoint", "token_endpoint", "jwks_uri")]
        for label, value in zip(("authorization endpoint", "token endpoint", "JWKS URI"), values):
            _https_url(value, label)
        return cls(expected_issuer, *values)


class OIDCIDTokenVerifier:
    """Verify JWT signatures and mandatory OIDC claims against a trusted JWKS."""
    def __init__(self, issuer: str, client_id: str, jwks: dict, *, clock: Callable[[], float] = time.time,
                 leeway_seconds: int = 60):
        _https_url(issuer, "issuer")
        if not client_id or leeway_seconds < 0 or leeway_seconds > 300:
            raise ValidationError("Invalid OIDC verifier configuration")
        keys = jwks.get("keys") if isinstance(jwks, dict) else None
        if not isinstance(keys, list) or not keys:
            raise ValidationError("OIDC JWKS must contain at least one key")
        self.issuer, self.client_id, self.keys = issuer, client_id, keys
        self.clock, self.leeway = clock, leeway_seconds

    def _key(self, header: dict):
        alg, kid = header.get("alg"), header.get("kid")
        if alg not in _ALLOWED_ALGORITHMS or not kid or header.get("crit"):
            raise AuthenticationRequired("Unsupported OIDC token signing header")
        matches = [k for k in self.keys if k.get("kid") == kid and k.get("use", "sig") == "sig" and k.get("alg", alg) == alg]
        if len(matches) != 1:
            raise AuthenticationRequired("OIDC signing key is missing or ambiguous")
        jwk = matches[0]
        try:
            if alg == "RS256" and jwk.get("kty") == "RSA":
                n, e = int.from_bytes(_b64u(jwk["n"]), "big"), int.from_bytes(_b64u(jwk["e"]), "big")
                key = rsa.RSAPublicNumbers(e, n).public_key()
                if key.key_size < 2048:
                    raise AuthenticationRequired("OIDC RSA signing key is too small (2048 bits are required)")
                return key, alg
            if alg == "ES256" and jwk.get("kty") == "EC" and jwk.get("crv") == "P-256":
                x, y = int.from_bytes(_b64u(jwk["x"]), "big"), int.from_bytes(_b64u(jwk["y"]), "big")
                return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key(), alg
        except (KeyError, ValueError, TypeError):
            pass
        raise AuthenticationRequired("OIDC signing key type does not match the algorithm")

    def verify(self, token: str, *, expected_nonce: str) -> dict:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError("not compact JWT")
            header, claims = _json_segment(parts[0]), _json_segment(parts[1])
            signature = _b64u(parts[2])
            key, alg = self._key(header)
            signing_input = (parts[0] + "." + parts[1]).encode("ascii")
            if alg == "RS256":
                key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
            else:
                if len(signature) != 64:
                    raise ValueError("invalid ES256 signature length")
                r = int.from_bytes(signature[:32], "big")
                s = int.from_bytes(signature[32:], "big")
                key.verify(encode_dss_signature(r, s), signing_input, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            raise AuthenticationRequired("OIDC identity token signature is invalid") from None
        except AuthenticationRequired:
            raise
        except Exception:
            raise AuthenticationRequired("OIDC identity token is malformed") from None

        now = int(self.clock())
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if claims.get("iss") != self.issuer or self.client_id not in audiences:
            raise AuthenticationRequired("OIDC issuer or audience validation failed")
        if len(audiences) > 1 and claims.get("azp") != self.client_id:
            raise AuthenticationRequired("OIDC authorized-party validation failed")
        if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= now - self.leeway:
            raise AuthenticationRequired("OIDC identity token has expired")
        if not isinstance(claims.get("iat"), (int, float)) or claims["iat"] > now + self.leeway:
            raise AuthenticationRequired("OIDC identity token issued-at time is invalid")
        if "nbf" in claims and (not isinstance(claims["nbf"], (int, float)) or claims["nbf"] > now + self.leeway):
            raise AuthenticationRequired("OIDC identity token is not yet valid")
        if not claims.get("sub") or not expected_nonce or claims.get("nonce") != expected_nonce:
            raise AuthenticationRequired("OIDC subject or nonce validation failed")
        return claims


def verify_oidc_login(verifier: OIDCIDTokenVerifier, id_token: str, *, expected_nonce: str) -> dict:
    """Return normalized verified identity claims suitable for account linking."""
    claims = verifier.verify(id_token, expected_nonce=expected_nonce)
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise AuthenticationRequired("Identity provider must supply a verified email address")
    return {"issuer": verifier.issuer, "subject": str(claims["sub"]),
            "email": str(claims["email"]).strip().lower(), "name": str(claims.get("name") or "")}
