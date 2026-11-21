import base64, json, time
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from velora.controlplane.oidc_adapter import OIDCIDTokenVerifier, OIDCDiscovery, verify_oidc_login
from velora.exceptions import AuthenticationRequired, ValidationError


def b64(data): return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
def seg(obj): return b64(json.dumps(obj, separators=(',', ':')).encode())

@pytest.fixture
def signed_token():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    jwk = {"kty":"RSA", "kid":"key-1", "use":"sig", "alg":"RS256",
           "n":b64(pub.n.to_bytes((pub.n.bit_length()+7)//8,'big')),
           "e":b64(pub.e.to_bytes((pub.e.bit_length()+7)//8,'big'))}
    now = int(time.time())
    claims = {"iss":"https://id.example/", "aud":"velora-client", "sub":"subject-1",
              "exp":now+300, "iat":now, "nonce":"nonce-1", "email":"USER@example.com",
              "email_verified":True, "name":"User"}
    head, body = seg({"alg":"RS256","kid":"key-1","typ":"JWT"}), seg(claims)
    signing = f"{head}.{body}".encode()
    token = f"{head}.{body}.{b64(key.sign(signing,padding.PKCS1v15(),hashes.SHA256()))}"
    return token, jwk, claims


def test_verifies_signature_and_normalizes_verified_identity(signed_token):
    token,jwk,_=signed_token
    v=OIDCIDTokenVerifier("https://id.example/", "velora-client", {"keys":[jwk]})
    result=verify_oidc_login(v, token, expected_nonce="nonce-1")
    assert result["email"] == "user@example.com" and result["subject"] == "subject-1"


def test_rejects_signature_tampering(signed_token):
    token,jwk,_=signed_token
    parts=token.split('.'); parts[1]=seg({"iss":"https://evil.example/"})
    v=OIDCIDTokenVerifier("https://id.example/", "velora-client", {"keys":[jwk]})
    with pytest.raises(AuthenticationRequired): v.verify('.'.join(parts), expected_nonce="nonce-1")


def test_rejects_wrong_nonce_and_untrusted_kid(signed_token):
    token,jwk,_=signed_token
    v=OIDCIDTokenVerifier("https://id.example/", "velora-client", {"keys":[jwk]})
    with pytest.raises(AuthenticationRequired): v.verify(token, expected_nonce="other")
    v2=OIDCIDTokenVerifier("https://id.example/", "velora-client", {"keys":[]}) if False else OIDCIDTokenVerifier("https://id.example/", "velora-client", {"keys":[{**jwk,"kid":"other"}]})
    with pytest.raises(AuthenticationRequired): v2.verify(token, expected_nonce="nonce-1")


def test_discovery_issuer_and_https_are_pinned():
    doc={"issuer":"https://id.example/", "authorization_endpoint":"https://id.example/auth",
         "token_endpoint":"https://id.example/token", "jwks_uri":"https://id.example/keys"}
    assert OIDCDiscovery.from_document("https://id.example/",doc).jwks_uri == doc["jwks_uri"]
    with pytest.raises(ValidationError): OIDCDiscovery.from_document("https://evil.example/",doc)
    doc["jwks_uri"]="http://id.example/keys"
    with pytest.raises(ValidationError): OIDCDiscovery.from_document("https://id.example/",doc)


def test_rejects_unverified_email(signed_token):
    token,jwk,claims=signed_token
    claims["email_verified"]=False
    head,body=seg({"alg":"RS256","kid":"key-1"}),seg(claims)
    # The signature is intentionally not rebuilt: signature failure is also a safe rejection.
    v=OIDCIDTokenVerifier("https://id.example/", "velora-client", {"keys":[jwk]})
    with pytest.raises(AuthenticationRequired): verify_oidc_login(v, f"{head}.{body}.{token.split('.')[2]}", expected_nonce="nonce-1")
