# Final release checklist — Velora ProjectOne Mobile v1.4.0

## What is complete in the supplied source

- Velora Framework native password/session authentication integration.
- Optional TOTP code submitted to the existing Velora authentication endpoint.
- SecureStore storage for the returned bearer token and active company.
- Session restoration through the Framework's `/api/auth/me`.
- Company switching through `/api/auth/switch-company`; server authorisation remains authoritative.
- Server-side logout and local credential cleanup.
- HTTPS-only API base configuration.
- Five colour themes and Light/Dark/System appearance modes.
- Staging qualification runner that does not print credentials or tokens.
- Automated mobile tests and build configuration checks.

## Additional source hardening in this handoff

- Added `tsconfig.json` extending Expo's TypeScript base configuration. The previous bundle did not contain a TypeScript project configuration, so `tsc --noEmit` could not be meaningfully run.
- Updated the EAS app config to accept `EXPO_PROJECT_ID` at build time rather than inventing a project identifier.
- Updated Android preview GitHub Actions workflow to verify tests, build configuration, TypeScript, EAS token and EAS project linkage before requesting an APK build.

## Required deployment inputs (must be supplied by the deployment owner)

1. Actual HTTPS staging API origin, replacing the example `https://projectone.yourdomain.com`.
2. Expo EAS project ID, stored as GitHub repository variable `EXPO_PROJECT_ID`.
3. Expo access token, stored as GitHub Actions secret `EXPO_TOKEN`.
4. Dedicated staging test account and (if enabled) TOTP code supplied only to the local staging runner.
5. At least two authorised company memberships if company-switch testing is required.
6. Production API origin and approved release environment after staging sign-off.
7. Android signing / Google Play ownership for store distribution. EAS manages signing only when configured for the linked Expo project.

## Run locally

```bash
cd mobile
npm install
npm test
npm run check:build-config
npm run typecheck
```

Set the staging API origin and a dedicated test account in the local shell, then run:

```bash
node scripts/qualify-staging.mjs
```

The staging runner creates a real server session and revokes it. Never run it against production unless explicitly approved.

## Configure GitHub Actions

Repository variable:
- `EXPO_PUBLIC_PROJECTONE_API_BASE` — actual HTTPS API origin for the preview build. Placeholder hosts such as `projectone.yourdomain.com` are rejected by the release gate.
- `EXPO_PROJECT_ID` — existing Expo/EAS project UUID.

Repository secret:
- `EXPO_TOKEN` — Expo access token.

Then run the `ProjectOne Mobile Android Preview` workflow manually. The workflow installs dependencies, runs tests and typecheck, then submits the Android APK build to EAS. Download the APK from the EAS build page linked in the workflow output.

## Acceptance tests before release

- Install APK on at least one physical Android device.
- Password sign-in with an ordinary Velora user.
- TOTP sign-in with an MFA-enabled user.
- Session restore after app restart.
- Session expiry/revocation returns user to sign-in.
- Multi-company user switches between authorised companies.
- Company-specific project list, approvals, comments and workflow actions respect server permissions.
- User cannot switch into an unauthorised company.
- Logout revokes the server token and clears local credentials.
- Confirm no ProjectOne mobile action writes GL, Journal Entries, Payroll or other authoritative finance records.
- Complete user acceptance testing and obtain release approval.

## Current status and limits

Offline mobile tests: 29/29 passed after the final configuration hardening. Build configuration and JavaScript syntax checks passed. The Framework authentication hardening test file was independently executed: 10 passed.

A full dependency-backed TypeScript check and native APK build have not been completed in this environment because npm dependency installation did not complete. Live staging API tests, PostgreSQL deployment qualification and physical-device tests also remain dependent on the deployment inputs and environments above. This package must not be described as production-certified until those gates pass.
