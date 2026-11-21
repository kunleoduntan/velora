"""Provider discovery, JWKS retrieval and authorization-code exchange for Velora v0.31.

Network I/O is injected so deployments can use their vetted HTTP client,
strict timeouts, TLS verification and outbound-network policy. No redirects
are accepted by this adapter; URLs are checked against an explicit host set.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Callable

from ..exceptions import AuthenticationRequired, ValidationError
from .oidc_adapter import OIDCDiscovery, OIDCIDTokenVerifier, verify_oidc_login


def _check_host(url: str, allowed_hosts: set[str], label: str) -> None:
    p = urlparse(url or "")
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.hostname.lower() not in allowed_hosts:
        raise ValidationError(f"OIDC {label} host is not in the configured HTTPS allowlist")
    if p.port not in (None, 443):
        raise ValidationError(f"OIDC {label} must use the standard HTTPS port")


@dataclass(frozen=True)
class OIDCProviderMetadata:
    discovery: OIDCDiscovery
    jwks: dict


class OIDCProviderClient:
    """Fetch provider metadata and exchange authorization codes via injected transport.

    fetch_json(url) and post_form(url, data) must enforce short connect/read
    timeouts, TLS certificate validation, response-size limits and no redirects.
    """
    def __init__(self, issuer: str, client_id: str, allowed_hosts: set[str],
                 fetch_json: Callable[[str], dict], post_form: Callable[[str, dict], dict]):
        self.issuer, self.client_id = issuer.rstrip("/"), client_id
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.fetch_json, self.post_form = fetch_json, post_form
        if not client_id or not self.allowed_hosts:
            raise ValidationError("OIDC client ID and explicit host allowlist are required")
        _check_host(self.issuer, self.allowed_hosts, "issuer")

    def load_metadata(self) -> OIDCProviderMetadata:
        issuer = self.issuer
        # OIDC discovery path is appended to the issuer path, preserving tenant paths.
        url = issuer + "/.well-known/openid-configuration"
        document = self.fetch_json(url)
        discovery = OIDCDiscovery.from_document(issuer, document)
        for label, endpoint in (("authorization", discovery.authorization_endpoint),
                                ("token", discovery.token_endpoint), ("JWKS", discovery.jwks_uri)):
            _check_host(endpoint, self.allowed_hosts, label)
        jwks = self.fetch_json(discovery.jwks_uri)
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list) or not jwks["keys"]:
            raise AuthenticationRequired("Identity provider returned an invalid JWKS document")
        return OIDCProviderMetadata(discovery, jwks)

    def exchange_and_verify(self, *, code: str, redirect_uri: str, code_verifier: str,
                            nonce: str, metadata: OIDCProviderMetadata) -> dict:
        if not code or not code_verifier or not nonce:
            raise AuthenticationRequired("OIDC authorization response is incomplete")
        endpoint = metadata.discovery.token_endpoint
        _check_host(endpoint, self.allowed_hosts, "token")
        response = self.post_form(endpoint, {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": redirect_uri, "client_id": self.client_id,
            "code_verifier": code_verifier,
        })
        if not isinstance(response, dict) or not response.get("id_token"):
            raise AuthenticationRequired("Identity provider did not return an ID token")
        verifier = OIDCIDTokenVerifier(self.issuer, self.client_id, metadata.jwks)
        return verify_oidc_login(verifier, response["id_token"], expected_nonce=nonce)
