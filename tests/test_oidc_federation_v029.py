import pytest
from velora.exceptions import AuthenticationRequired, ValidationError
from velora.controlplane.federation import OIDCProvider, OIDCFederation

class Clock:
    value = 1_800_000_000
    def __call__(self): return self.value

@pytest.fixture
def setup_oidc():
    clock=Clock()
    provider=OIDCProvider("entra", "https://login.microsoftonline.com/example/v2.0", "https://login.microsoftonline.com/example/oauth2/v2.0/authorize", "client-123", "https://app.example.com/auth/oidc/callback")
    return clock, OIDCFederation({"entra":provider}, clock=clock)

def test_begin_uses_pkce_s256_nonce_and_state(setup_oidc):
    _, oidc=setup_oidc
    tx=oidc.begin("entra")
    assert "code_challenge_method=S256" in tx.authorization_url
    assert tx.state and tx.nonce and len(tx.code_verifier) >= 43

def test_transaction_is_one_use(setup_oidc):
    _, oidc=setup_oidc
    tx=oidc.begin("entra")
    assert oidc.consume(tx.state,"entra")["nonce"] == tx.nonce
    with pytest.raises(AuthenticationRequired): oidc.consume(tx.state,"entra")

def test_wrong_provider_and_expired_transaction_fail(setup_oidc):
    clock, oidc=setup_oidc
    tx=oidc.begin("entra")
    with pytest.raises(AuthenticationRequired): oidc.consume(tx.state,"other")
    tx=oidc.begin("entra"); clock.value += 301
    with pytest.raises(AuthenticationRequired): oidc.consume(tx.state,"entra")

def test_verified_claims_require_issuer_audience_exp_nonce_and_verified_email(setup_oidc):
    clock, oidc=setup_oidc
    claims={"iss":"https://login.microsoftonline.com/example/v2.0","aud":"client-123","exp":clock.value+300,"sub":"abc","nonce":"n","email":"USER@example.com","email_verified":True,"name":"User"}
    result=oidc.validate_verified_claims("entra",claims,"n")
    assert result["email"] == "user@example.com"
    for key, value in (("iss","https://evil.example"),("aud","other"),("nonce","wrong"),("email_verified",False),("exp",clock.value-1)):
        bad={**claims,key:value}
        with pytest.raises(AuthenticationRequired): oidc.validate_verified_claims("entra",bad,"n")

def test_provider_requires_https_and_openid_scope():
    with pytest.raises(ValidationError):
        OIDCProvider("x","http://issuer","https://idp.example/auth","client","https://app.example/cb").validate()
    with pytest.raises(ValidationError):
        OIDCProvider("x","https://issuer","https://idp.example/auth","client","https://app.example/cb",("email",)).validate()
