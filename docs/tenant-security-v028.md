# Velora v0.28 — Tenant security boundary

## What changed

- Added `velora.tenant_security.resolve_tenant_company()` as the single tenant-aware authorization boundary for authenticated platform requests.
- The boundary revalidates the user's company membership through the control plane on each request, checks tenant and company lifecycle status, and returns an immutable context containing the tenant, company and company-specific roles.
- Supports an optional `expected_tenant_id` pin for future tenant-scoped API credentials. The tenant value is an additional constraint, never proof of membership.
- Added `assert_same_tenant()` for services that handle tenant-owned metadata or resources.
- Integrated the boundary into the normal cookie/Bearer user request scope before selecting and binding a company database.
- Preserves the existing per-company database model: the control plane stores identity and routing metadata; business records remain in each company's database.

## Existing authentication reused

Velora already provides password authentication, opaque server-side sessions, per-company role assignments, tenant/company suspension checks, HttpOnly cookies, CSRF protection for cookie-authenticated mutations, company-specific API keys, and optional authenticator-app TOTP MFA. v0.28 hardens the point where authenticated identity becomes an authorized tenant/company database context; it does not replace those mechanisms.

## Usage

```python
from velora.tenant_security import resolve_tenant_company, assert_same_tenant

context = resolve_tenant_company(plane, auth, requested_company_id)
# Optional extra restriction for a tenant-pinned integration credential:
context = resolve_tenant_company(plane, auth, requested_company_id,
                                 expected_tenant_id="TEN-001")
assert_same_tenant(context, resource_tenant_id)
```

Do not accept a `tenant_id` supplied by a browser as authorization. Always resolve the user's membership and company from the control plane first. Do not set a process-global active company/database; use the existing request-scoped `site` and `company_context` bindings.

## Verification

- `tests/test_tenant_security_v028.py`: 4 tenant-boundary tests.
- `tests/test_security_v027.py`: 5 security regression tests.
- `tests/test_platform.py` and `tests/test_api.py`: 47 passed, 4 skipped.
- Python compilation completed successfully.
- The complete repository test run exceeded the execution time limit; it did not complete and must not be represented as a full-suite pass.

## Explicit limitations

- OIDC/SAML federation and enterprise identity-provider discovery are not implemented in this release.
- TOTP MFA is already available in the control-plane identity service; v0.28 does not add WebAuthn/passkeys, recovery codes or organization-wide MFA enforcement policies.
- The new tenant boundary is integrated into the normal authenticated user request scope. The separately scoped company API-key path retains its existing company-key validation and is not silently treated as an OIDC or tenant-wide credential.
- Production deployment still requires HTTPS, secure secret/key backup, database least-privilege credentials, monitoring and a reviewed tenant-isolation test plan.
