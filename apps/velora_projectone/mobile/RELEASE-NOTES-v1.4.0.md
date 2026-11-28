# Velora ProjectOne Mobile v1.4.0

## Velora Framework native authentication integration

- Replaced the placeholder OIDC Authorization Code + PKCE flow with the existing Velora Framework control-plane password sign-in endpoint.
- Supports optional authenticator-app TOTP codes using Velora's existing MFA verifier.
- Requests the existing opaque Velora session token using `return_token: true`.
- Persists session token and selected company ID using Expo SecureStore.
- Restores sessions through `GET /api/auth/me`; expired/revoked sessions return the user to sign-in.
- Adds server-side logout through `POST /api/auth/logout`.
- Adds company selection and switching through the existing `/api/auth/switch-company` endpoint.
- Sends bearer session token and selected company context on ProjectOne API calls.
- Removed external OIDC discovery/client configuration and related mobile dependencies.
- Updated build validation to require only the configurable HTTPS Velora API base URL.

## Preserved functionality

- ProjectOne v2.15.0 integration remains unchanged.
- Five colour themes and Light / Dark / System appearance remain available.
- Executive dashboard, projects, workbench, approvals, notes and non-submitting timesheet helper remain in place.

## Security boundary

Velora Framework v1.13.0 remains authoritative for credential verification, account lockout, MFA, session expiry/revocation, company membership and company-specific role resolution. The mobile client does not create or assert user, actor, role or permission identities.
