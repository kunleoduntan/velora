import pytest
from velora.controlplane.oidc_client import OIDCProviderClient
from velora.exceptions import ValidationError, AuthenticationRequired

ISSUER = "https://login.example.test/tenant"
DOC = {"issuer": ISSUER, "authorization_endpoint": "https://login.example.test/authorize",
       "token_endpoint": "https://login.example.test/token", "jwks_uri": "https://login.example.test/keys"}

def test_discovery_and_jwks_are_loaded_only_from_allowlisted_https_hosts():
    calls=[]
    def fetch(url):
        calls.append(url); return DOC if "well-known" in url else {"keys":[{"kid":"k"}]}
    c=OIDCProviderClient(ISSUER,"client",{"login.example.test"},fetch,lambda u,d:{})
    meta=c.load_metadata()
    assert meta.discovery.issuer == ISSUER and len(meta.jwks["keys"]) == 1
    assert calls[0] == ISSUER + "/.well-known/openid-configuration"

def test_rejects_discovery_endpoint_outside_allowlist():
    def fetch(url):
        return {**DOC,"jwks_uri":"https://attacker.test/keys"} if "well-known" in url else {"keys":[{}]}
    c=OIDCProviderClient(ISSUER,"client",{"login.example.test"},fetch,lambda u,d:{})
    with pytest.raises(ValidationError): c.load_metadata()

def test_rejects_missing_code_or_token():
    c=OIDCProviderClient(ISSUER,"client",{"login.example.test"},lambda u:{},lambda u,d:{})
    from velora.controlplane.oidc_adapter import OIDCDiscovery
    meta=type("M",(),{"discovery":OIDCDiscovery.from_document(ISSUER,DOC),"jwks":{"keys":[{}]}})()
    with pytest.raises(AuthenticationRequired):
        c.exchange_and_verify(code="",redirect_uri="https://app.example/cb",code_verifier="v",nonce="n",metadata=meta)

def test_requires_explicit_https_host_allowlist():
    with pytest.raises(ValidationError):
        OIDCProviderClient("http://login.example.test","client",{"login.example.test"},lambda u:{},lambda u,d:{})
