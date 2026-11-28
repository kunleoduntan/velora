# Velora ProjectOne Mobile 1.4.0

React Native / Expo companion app for **Velora ProjectOne server v2.25.2**, integrated with **Velora Framework v1.16.1** authentication.

## Authentication and session lifecycle

The mobile app reuses Velora's existing control-plane identity service. It does not introduce an external identity provider, duplicate user directory or parallel password store.

- `POST /api/auth/login` with `email`, `password`, optional `totp_code`, and `return_token: true`.
- The response contains the existing Velora profile and opaque session token.
- The token is stored using iOS Keychain / Android Keystore through `expo-secure-store`.
- `GET /api/auth/me` validates/restores the server session on app launch.
- `POST /api/auth/switch-company` asks Velora to authorize and persist the selected company.
- Business API calls send `Authorization: Bearer <opaque-session-token>` and `X-Velora-Company: <selected-company-id>`.
- `POST /api/auth/logout` revokes the server session; local secure storage is then cleared.
- Optional TOTP is passed to the existing Velora MFA verifier. Users without MFA leave the code blank.
- Server-side password policy, lockout, IP throttling, session expiry, account activation, company membership, role resolution and request authorization remain authoritative.

Velora stores only the SHA-256 hash of its opaque session token. The mobile client never sends actor IDs, role IDs or permission claims. The company header is a requested company context only; the server verifies membership and active status before routing a request to that company's database.

## Interface and capabilities

- Velora navy, blue and pink visual system, with five selectable colour palettes and Light / Dark / System appearance.
- Executive portfolio snapshot.
- Searchable project directory and project workbench, including task lanes and append-only project notes.
- Workflow approval inbox with explicit confirmation and server-validated actions.
- Weekly-hours planning helper; it does not create or submit a timesheet.
- Integration readiness, account and company switcher, app information and sign-out.
- Accessible navigation labels, loading, retry and empty states.

## Configure

The default API base is `https://projectone.yourdomain.com`, as previously specified. Override it per environment with:

`EXPO_PUBLIC_PROJECTONE_API_BASE=https://your-velora-host.example`

Authentication uses the same Velora API host. No OIDC discovery URL, external identity-provider client ID or mobile client secret is required. HTTPS is enforced by the build configuration.

## Local development and validation

Requires Node.js compatible with Expo SDK 54 and the native toolchain for the target platform.

```bash
cd mobile
npm install
npm test
npm run check:build-config
npm run typecheck
npx expo start
```

Native builds:

```bash
npx expo prebuild --platform android
npx expo run:android
npx expo prebuild --platform ios
npx expo run:ios
```

EAS preview and production profiles remain configured in `eas.json`. The source package does not contain signed APK/AAB/IPA binaries. Configure EAS project identity and platform signing credentials before producing distributable builds.

## API usage

Authentication:
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/switch-company`
- `POST /api/auth/logout`

ProjectOne:
- `GET /api/projectone/portfolio/executive-workspace`
- `GET /api/projectone/native/documents/Project`
- `GET /api/projectone/workbench/projects/{project_id}`
- `GET /api/projectone/native/workflow-inbox`
- `POST /api/projectone/native/workflow/{doctype}/{name}/{action}`
- `GET /api/projectone/integrations/readiness`
- `POST /api/projectone/tasks/{task_id}/comments`

## Operating boundaries

- ProjectOne remains the source of project and programme records.
- Velora Framework remains the source of identity, sessions, company membership and permission enforcement.
- The mobile app does not create General Ledger entries, Journal Entries, payroll, HRMS or inventory transactions.
- No offline mutation queue is enabled; mutations require a live authenticated server session.
- A successful local test suite does not prove DNS, TLS, production endpoint availability, native compilation, device compatibility or UAT.
