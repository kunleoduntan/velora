# Validation — ProjectOne Mobile v1.4.0

## Source baseline inspected

- Velora Framework: **v1.13.0**
- VeloraERP: **v2.89.0**
- ProjectOne server: **v2.15.0**
- Mobile: **v1.4.0**

The uploaded clean repository archive was inspected. The integration uses existing Framework routes and did not add or alter Framework or ERP authentication endpoints.

## Implemented contract

- Password login: `POST /api/auth/login` with `return_token: true`.
- Optional authenticator code: `totp_code`, passed to the existing Framework identity verifier.
- Session restore: `GET /api/auth/me`.
- Company switch: `POST /api/auth/switch-company`.
- Logout: `POST /api/auth/logout`.
- Business API requests: bearer session token and `X-Velora-Company`.
- Token storage: Expo SecureStore.
- Session rejection: HTTP 401 clears local credentials and returns the app to sign-in.

The Framework remains responsible for credential validation, account and IP lockout, optional MFA, session expiry/revocation, company membership, active-company validation and company-specific role resolution.

## Automated results

| Validation | Result |
|---|---:|
| Mobile automated tests | **25 passed, 0 failed** |
| Mobile build-config validation | Passed |
| Framework auth/platform tests | **50 passed, 4 skipped** |
| ProjectOne server source changes | None |
| Framework / ERP source changes | None |

The Framework test run used `tests/test_platform.py` and `tests/test_auth_hardening.py`. Four tests were skipped by the source test suite.

## Not yet verified

- Full TypeScript typecheck: dependencies are not installed in this packaging environment. A compiler parse/check was attempted; remaining diagnostics are missing installed React / React Native / Expo modules and typings.
- Expo prebuild and Android native compilation.
- Signed APK, AAB or iOS IPA generation.
- Live DNS/TLS/API connectivity to `https://projectone.yourdomain.com`.
- Physical-device login, MFA, session expiry, logout and company-switch UAT.
- Production deployment and security acceptance.

The successful automated tests validate the implemented client contract and the existing Framework auth route behaviour. They do not constitute live deployment or device qualification.
