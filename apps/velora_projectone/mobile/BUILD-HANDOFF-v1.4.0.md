# Build handoff — ProjectOne Mobile v1.4.0

## Required environment

The mobile app uses the Velora API host for both authentication and ProjectOne data.

```dotenv
EXPO_PUBLIC_PROJECTONE_API_BASE=https://projectone.yourdomain.com
```

Override this variable for staging or development. HTTPS is required by the build validator.

## Identity and account setup

- No external identity-provider registration is required for this version.
- Use existing Velora control-plane users.
- Grant each user active membership in the appropriate company or companies.
- If MFA is enabled for a user, the user must enter the current six-digit authenticator code at sign-in.
- Confirm the API hostname routes to the Velora Framework v1.13.0 deployment and that its TLS certificate is valid.
- Confirm CORS / gateway policy permits the native app's HTTPS requests where applicable.

## Build

```bash
cd mobile
npm install
npm test
npm run check:build-config
npm run typecheck
eas build --platform android --profile preview
```

The preview profile is configured for an internal APK. Production Android uses the AAB profile. iOS requires Apple signing and provisioning.

## Release gates

1. Install the preview APK on a physical Android device.
2. Sign in with a standard Velora user.
3. Verify sign-in with a user whose TOTP MFA is enabled.
4. Verify an account with multiple company memberships can choose and switch companies.
5. Verify project lists and workflow inboxes reflect the selected company's permissions.
6. Verify invalid credentials, account lockout and expired/revoked sessions are handled by Velora.
7. Verify sign-out revokes the server session; confirm the token cannot be reused.
8. Repeat on iOS before publishing the iOS app.

Do not ship to production until device testing and live endpoint qualification are complete.
